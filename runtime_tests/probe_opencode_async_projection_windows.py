"""One actual OpenCode response through Node SQLite, Temporal and PostgreSQL."""
from __future__ import annotations

import asyncio
import json
import os
import sqlite3
import time
import uuid
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo

from runtime.codex_driver import (
    AuthorizedOperation,
    BindingIdentity,
    DriverJournal,
    DriverRejected,
    OutcomeUncertain,
    file_digest,
)
from runtime.human_bridge_file_provider import _sha256
from runtime.native_delivery import NativeDeliveryAdapter
from runtime.node import NodeJournal
from runtime.opencode_driver import OpenCodeLaunchProfile, OpenCodeNativeDriver
from runtime.receiver_delivery import ReceiverNativeDeliveryBridge
from runtime.recovery import NodeResponseOutbox, ProjectionDisposition
from runtime.recovery_models import canonical_digest
from runtime.recovery_service import RecoveryService
from runtime.response_collector import NativeResponseCollector
from runtime.supervisor import WindowsJobSupervisor
from runtime.temporal import TemporalAdapter
from runtime_tests.test_recovery_formal_integration import command, recovery_domain


async def project_after_temporal_restart(collector, projection_id, endpoint, namespace, queue):
    first = TemporalAdapter(
        endpoint, namespace=namespace, task_queue=queue, response_collector=collector,
    )
    await first.connect(start_worker=False)
    initial = await first.submit_response_projection(projection_id)
    initial_run_id = initial.first_execution_run_id
    await first.close()
    second = TemporalAdapter(
        endpoint, namespace=namespace, task_queue=queue, response_collector=collector,
    )
    await second.connect(start_worker=True)
    try:
        recovered = await second.submit_response_projection(projection_id)
        result = await asyncio.wait_for(recovered.result(), timeout=60)
        description = await recovered.describe()
        return initial_run_id, description.run_id, result
    finally:
        await second.close()


def main() -> int:
    if os.name != "nt":
        raise RuntimeError("actual OpenCode probe requires Windows Job containment")
    base_dsn = os.environ["ACS_INTEGRATION_DSN"]
    temporal_endpoint = os.environ["ACS_INTEGRATION_TEMPORAL"]
    temporal_namespace = os.environ.get("ACS_INTEGRATION_TEMPORAL_NAMESPACE", "default")
    root = Path(os.environ["ACS_INTEGRATION_EVIDENCE_ROOT"]).resolve()
    root.mkdir(parents=True, exist_ok=False)
    for name in ("home", "config", "data", "state", "cache", "input", "tmp"):
        (root / name).mkdir()
    config_dir = root / "config" / "opencode"
    config_dir.mkdir()
    config = {
        "$schema": "https://opencode.ai/config.json",
        "autoupdate": False,
        "share": "disabled",
        "permission": {"*": "deny", "task": "deny"},
        "default_agent": "acs-engineer",
        "model": "opencode/big-pickle",
        "agent": {
            "acs-engineer": {
                "description": "Controlled Runtime response projection",
                "mode": "primary",
                "model": "opencode/big-pickle",
                "permission": {"*": "deny", "task": "deny"},
            },
        },
    }
    config_path = config_dir / "opencode.json"
    config_path.write_text(json.dumps(config), encoding="utf-8")
    (root / "input" / "authorized.txt").write_text(
        "Owned synthetic input for one tool-disabled model turn.\n", encoding="utf-8",
    )
    binary = Path(
        "D:/common/develop/Nodejs/node_global/node_modules/opencode-ai/"
        "node_modules/opencode-windows-x64/bin/opencode.exe"
    )
    schema_path = Path(__file__).with_name("schema-1.18.27") / "opencode-openapi.json"
    profile = OpenCodeLaunchProfile(
        str(binary), file_digest(binary), "1.18.27", str(schema_path), file_digest(schema_path),
        str(root / "input"), str(root / "home"), str(root / "config"),
        str(root / "data"), str(root / "state"), str(root / "cache"), str(root / "tmp"),
        file_digest(config_path), "acs-engineer", "opencode", "big-pickle",
        {"SystemRoot": os.environ.get("SystemRoot", r"C:\Windows"),
         "PATH": str(binary.parent) + os.pathsep + r"C:\Windows\System32"},
    )
    schema_name = "async_model_" + uuid.uuid4().hex
    with psycopg.connect(base_dsn, autocommit=True) as admin:
        admin.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema_name)))
    dsn = make_conninfo(
        base_dsn,
        options=f"-c search_path={schema_name} -c statement_timeout=15000 -c lock_timeout=10000",
    )
    authority, _envelope, invocation = recovery_domain.__wrapped__(dsn)
    driver_journal = DriverJournal(root / "driver.sqlite")
    identity = BindingIdentity("node", "boot", "runtime", "attempt", "local-slot", 1)
    allowed = {"spawn", invocation.invocation_id, "terminate"}

    def authorize(operation, binding):
        operation.validate()
        if operation.operation_id not in allowed or binding != identity:
            raise DriverRejected("actual probe operation is outside its fixed binding")

    driver = OpenCodeNativeDriver(
        "async-projection-binding", profile, driver_journal, identity=identity,
        check_current=authorize, supervisor=WindowsJobSupervisor(),
        http_timeout=30, readback_attempts=8,
    )
    evidence = {
        "schema_version": "acs-async-response-model-evidence/1",
        "source_baseline": "a942e6a292d2d2bebbaa8389a7deabe03798fac1",
        "driver": file_digest(Path(__import__("runtime.opencode_driver").opencode_driver.__file__)),
        "binding": asdict(identity),
        "model": "opencode/big-pickle",
        "prompt_count": 0,
        "native_invoked": False,
        "core_restart": False,
        "node_projection_restart": False,
        "temporal_client_worker_restart": False,
    }
    try:
        driver.spawn(AuthorizedOperation(
            "spawn", "spawn-command", "spawn-message", "grant",
            datetime.now(UTC) + timedelta(minutes=2),
        ))
        adapter = NativeDeliveryAdapter(
            driver,
            authorize_invocation=lambda value, _binding: AuthorizedOperation(
                value.invocation_id, value.command_id, value.message_id,
                value.envelope.grant_ref, value.envelope.packet.deadline,
            ),
        )
        node = NodeJournal(
            root / "node.sqlite", machine_id="machine", node_id="node",
            boot_incarnation="boot",
        )
        outbox = node.response_outbox()
        terminal_values = []

        def store(value):
            terminal_values.append(value)
            digest_value = canonical_digest(value)
            return "artifact:" + digest_value, digest_value

        captured = []

        def fail_first_projection(observation):
            captured.append(observation)
            raise RuntimeError("injected Core loss before Domain projection")

        collector = NativeResponseCollector(adapter, outbox, store, fail_first_projection)
        ledger = root / "receiver.sqlite"
        with sqlite3.connect(ledger) as connection:
            connection.execute(
                "CREATE TABLE receiver_requests(operation_id TEXT,attempt_id TEXT,dispatch_id TEXT,"
                "purpose TEXT,body_json TEXT)"
            )
            connection.execute(
                "INSERT INTO receiver_requests VALUES (?,?,?,?,?)",
                (invocation.operation_id, invocation.attempt_id, invocation.dispatch_id,
                 "delivery.prepare", json.dumps({"invocation": invocation.model_dump(mode="json")})),
            )
        admission = SimpleNamespace(
            operation_id=invocation.operation_id, attempt_id=invocation.attempt_id,
            dispatch_id=invocation.dispatch_id, message_id=invocation.message_id,
            command_id=invocation.command_id,
        )
        bridge = ReceiverNativeDeliveryBridge(
            str(ledger), adapter, read_domain_marker=lambda _value: True,
            response_collector=collector,
        )
        bridge(admission)
        evidence["native_invoked"] = True
        deadline = time.monotonic() + 120
        while True:
            try:
                bridge.collect_response(admission)
            except OutcomeUncertain:
                if time.monotonic() >= deadline:
                    raise
                time.sleep(0.25)
                continue
            except RuntimeError as error:
                if str(error) != "injected Core loss before Domain projection":
                    raise
                break
            raise AssertionError("first Domain projection fault did not fire")
        assert len(captured) == 1 and len(outbox.recover()) == 1
        observation = captured[0]
        restarted_authority = type(authority)(dsn, context=authority.context)
        restarted_service = RecoveryService(restarted_authority)
        evidence["core_restart"] = True
        restarted_outbox = NodeResponseOutbox(root / "node.sqlite")
        evidence["node_projection_restart"] = True
        projection_payload = {"observation": observation.canonical()}
        projection_command = command(
            restarted_authority, "delivery.project_native_response",
            observation.projection_id, projection_payload, kind="projection",
            identity="actual-model",
        )

        def project(value):
            result = restarted_service.execute(
                projection_command, "delivery.project_native_response", projection_payload,
            )
            return ProjectionDisposition(
                value.projection_id, NodeResponseOutbox._payload(value)[1], result.state,
            )

        restarted_collector = NativeResponseCollector(
            adapter, restarted_outbox, store, project,
        )
        queue = "async-model-" + uuid.uuid4().hex
        first_run, recovered_run, temporal_result = asyncio.run(
            project_after_temporal_restart(
                restarted_collector, observation.projection_id,
                temporal_endpoint, temporal_namespace, queue,
            )
        )
        evidence["temporal_client_worker_restart"] = first_run == recovered_run
        evidence["temporal"] = {
            "workflow_id": "acs-response-projection/" + observation.projection_id,
            "run_id": recovered_run,
            "result": temporal_result,
        }
        consume_payload = {"projection_id": observation.projection_id, "scope_id": "local-scope"}
        consume_command = command(
            restarted_authority, "delivery.response.consume", observation.projection_id,
            consume_payload, kind="projection", identity="actual-consume",
        )
        first_consume = restarted_service.execute(
            consume_command, "delivery.response.consume", consume_payload,
        )
        replay_consume = restarted_service.execute(
            consume_command, "delivery.response.consume", consume_payload,
        )
        with restarted_authority._connect() as connection:
            projection = connection.execute(
                "SELECT disposition,native_outcome,response_digest,evidence_digest "
                "FROM native_response_observations WHERE projection_id=%s",
                (observation.projection_id,),
            ).fetchone()
            receipt_count = connection.execute(
                "SELECT count(*) FROM delivery_receipts WHERE message_id='message' "
                "AND layer='response_received'"
            ).fetchone()[0]
            consumption_count = connection.execute(
                "SELECT count(*) FROM native_response_consumptions WHERE projection_id=%s",
                (observation.projection_id,),
            ).fetchone()[0]
        terminal = terminal_values[0]
        evidence["projection"] = {
            "projection_id": observation.projection_id,
            "disposition": projection[0],
            "native_outcome": projection[1],
            "response_digest": projection[2],
            "evidence_digest": projection[3],
            "response_receipts": receipt_count,
            "consumptions": consumption_count,
            "consume_state": first_consume.state,
            "consume_replay_duplicate": replay_consume.duplicate,
        }
        evidence["assistant_text"] = terminal.get("assistant_text", [])
        evidence["expected_response_observed"] = (
            "".join(evidence["assistant_text"]).strip() == "ACS_P1_ASYNC_19_OK"
        )
        assert evidence["expected_response_observed"]
        assert projection[:2] == ("applied", "completed")
        assert receipt_count == 1 and consumption_count == 1
        assert restarted_outbox.recover() == ()
        evidence["result"] = "pass"
    except Exception as error:  # noqa: BLE001 - bounded evidence and mandatory cleanup
        evidence["result"] = "blocked"
        evidence["error"] = {"type": type(error).__name__, "message": str(error)[:500]}
    finally:
        if driver.owned:
            evidence["termination"] = driver.terminate(AuthorizedOperation(
                "terminate", "terminate-command", "terminate-message", "grant",
                datetime.now(UTC) + timedelta(minutes=2),
            ))
        driver.detach_transport()
        with driver_journal._connect() as connection:
            events = [json.loads(row[0]) for row in connection.execute(
                "SELECT body FROM driver_events WHERE kind='http_intent' ORDER BY sequence"
            )]
        evidence["prompt_count"] = sum(
            item["path"].endswith("/prompt_async") for item in events
        )
        evidence["http_methods"] = [item["method"] + " " + item["path"] for item in events]
        if (root / "node.sqlite").is_file():
            evidence["journal_sha256"] = _sha256((root / "node.sqlite").read_bytes())
        evidence_path = root / "evidence.json"
        evidence_path.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
        with psycopg.connect(base_dsn, autocommit=True) as admin:
            admin.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema_name)))
        print(json.dumps({
            "result": evidence["result"],
            "error": evidence.get("error"),
            "expected_response_observed": evidence.get("expected_response_observed"),
            "prompt_count": evidence["prompt_count"],
            "projection": evidence.get("projection"),
            "temporal_restart": evidence["temporal_client_worker_restart"],
            "termination": evidence.get("termination"),
            "evidence": str(evidence_path),
        }, indent=2))
    return 0 if evidence["result"] == "pass" else 2


if __name__ == "__main__":
    raise SystemExit(main())
