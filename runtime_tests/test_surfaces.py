"""Real SDK stdio, CLI subprocess and loopback HTTP conformance for local surfaces.

Non-PG tests execute actual processes with unavailable backend configuration.
PG tests require ACS_P1_DSN and own an isolated schema. Credentials are generated
per fixture and passed only by private process environment or loopback headers.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import secrets
import socket
import subprocess
import sys
import tempfile
import time
import uuid
from contextlib import contextmanager
from dataclasses import asdict, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import psycopg
import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp_types import (
    ClientCapabilities,
    Implementation,
    InitializedNotification,
    InitializeRequest,
    InitializeRequestParams,
    InitializeResult,
)
from psycopg import sql
from psycopg.conninfo import make_conninfo

from runtime.domain import DomainAuthority
from runtime.json_payload import bounded_payload
from runtime.models import AuthenticatedContext, CommandEnvelope
from runtime.surface_config import SurfaceSettings
from runtime.surfaces import PAYLOADS, SurfaceCommand

SOURCE = Path(__file__).resolve().parents[1]
PYTHON = os.environ.get("ACS_SURFACE_TEST_PYTHON", sys.executable)


def request(kind="work_item.create", target="surface-work", payload=None, revision=0, target_kind="work_item"):
    now = datetime.now(UTC)
    identity = uuid.uuid4().hex
    return {"command_type": kind, "target_id": target, "target_kind": target_kind, "expected_revision": revision,
            "command_id": f"surface-command-{identity}", "idempotency_key": f"surface-key-{identity}",
            "correlation_id": "surface-conformance", "issued_at": now.isoformat(),
            "deadline": (now + timedelta(minutes=5)).isoformat(), "payload": payload or {}}


def profile(tmp_path, *, dsn="postgresql://127.0.0.1:1/unavailable?connect_timeout=1", context=None, extra=None):
    secret = secrets.token_urlsafe(32)
    context = context or AuthenticatedContext("local-tenant", "acs-p1-authority", "local-1", "agent:surface", "grant:surface")
    context = replace(context, credential_hash=hashlib.sha256(secret.encode()).hexdigest())
    config = {"schema_version": "acs-surfaces/1", "context": asdict(context),
              "dsn_ref": {"kind": "environment", "name": "ACS_TEST_SURFACE_DSN"},
              "credential_ref": {"kind": "environment", "name": "ACS_TEST_SURFACE_TOKEN"}}
    if extra:
        config.update(extra)
    config_path = tmp_path / f"profile-{uuid.uuid4().hex}.json"
    config_path.write_text(json.dumps(config), encoding="utf-8")
    config_path.chmod(0o600)
    environment = dict(os.environ, ACS_TEST_SURFACE_DSN=dsn, ACS_TEST_SURFACE_TOKEN=secret,
                       PYTHONPATH=str(SOURCE) + os.pathsep + os.environ.get("PYTHONPATH", ""))
    return config_path, environment, secret


def process_command(config, environment, transport):
    bootstrap = environment.get("ACS_TEST_SURFACE_BOOTSTRAP")
    prefix = [PYTHON, bootstrap] if bootstrap else [PYTHON, "-m", "runtime.surface_entry"]
    return [*prefix, "--config", str(config), transport]


def cli(config, environment, value):
    completed = subprocess.run(process_command(config, environment, "cli"),
                               input=json.dumps(value).encode(), capture_output=True, env=environment, cwd=SOURCE, timeout=20, check=False)
    return completed, json.loads(completed.stdout)


async def sdk_call(config, environment, values, *, protocol="2025-11-25", tool="run"):
    command = process_command(config, environment, "mcp")
    parameters = StdioServerParameters(command=command[0], args=command[1:],
                                      env=environment, cwd=str(SOURCE))
    with tempfile.TemporaryFile(mode="w+", encoding="utf-8") as errors:
        async with stdio_client(parameters, errlog=errors) as streams, ClientSession(*streams, read_timeout_seconds=15) as session:
            if protocol == "2025-11-25":
                initialized = await session.initialize()
            else:
                initialized = await session.send_request(InitializeRequest(params=InitializeRequestParams(
                    protocol_version=protocol, capabilities=ClientCapabilities(),
                    client_info=Implementation(name="acs-surface-conformance", version="1"))), InitializeResult)
                session.adopt(initialized)
                await session.send_notification(InitializedNotification())
            tools = await session.list_tools()
            results = [await session.call_tool(tool, {"request": value}) for value in values]
        errors.seek(0)
        return initialized, tools, results, errors.read()


@contextmanager
def http_process(config, environment):
    with socket.socket() as available:
        available.bind(("127.0.0.1", 0))
        port = available.getsockname()[1]
    data = json.loads(config.read_text())
    data["port"] = port
    config.write_text(json.dumps(data))
    process = subprocess.Popen(process_command(config, environment, "http"),
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=environment, cwd=SOURCE)
    url = f"http://127.0.0.1:{port}"
    try:
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            if process.poll() is not None:
                pytest.fail("HTTP process exited before becoming available")
            try:
                if httpx.get(url + "/v1/health", timeout=0.3).status_code == 200:
                    break
            except httpx.HTTPError:
                pass
            time.sleep(0.02)
        else:
            pytest.fail("HTTP loopback process did not start")
        yield url
    finally:
        process.terminate()
        try:
            process.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.communicate(timeout=5)


@pytest.mark.parametrize("protocol", ["2025-06-18", "2025-11-25"])
def test_real_sdk_handshake_and_unauthenticated_tool(protocol, tmp_path):
    config, environment, secret = profile(tmp_path)
    environment.pop("ACS_TEST_SURFACE_TOKEN")
    initialized, tools, results, errors = asyncio.run(sdk_call(config, environment, [request()], protocol=protocol))
    assert initialized.protocol_version == protocol
    assert tools.tools[0].name == "run"
    assert results[0].is_error and results[0].structured_content["error"]["code"] == "UNAUTHENTICATED"
    assert secret not in errors and secret not in results[0].model_dump_json()


def test_real_cli_denies_missing_credential_without_echo(tmp_path):
    config, environment, secret = profile(tmp_path)
    environment.pop("ACS_TEST_SURFACE_TOKEN")
    process, value = cli(config, environment, request())
    assert process.returncode == 1 and value["error"]["code"] == "UNAUTHENTICATED"
    assert secret.encode() not in process.stdout + process.stderr


def test_real_loopback_http_denies_body_role_override_and_missing_header(tmp_path):
    config, environment, secret = profile(tmp_path)
    with http_process(config, environment) as url:
        assert httpx.post(url + "/v1/commands", json=request()).status_code == 401
        poisoned = request() | {"principal_ref": "privileged", "grant_ref": "forged"}
        result = httpx.post(url + "/v1/commands", json=poisoned, headers={"X-ACS-Credential": secret})
        assert result.status_code == 422 and result.json()["error"]["code"] == "INPUT_INVALID"
        assert secret not in result.text


def test_mcp_rejects_unknown_tool_and_does_not_echo_credential_as_invalid_input(tmp_path):
    config, environment, secret = profile(tmp_path)
    _, _, results, errors = asyncio.run(sdk_call(config, environment, [request() | {"grant_ref": secret}]))
    assert results[0].is_error and secret not in results[0].model_dump_json() and secret not in errors
    _, _, unknown, _ = asyncio.run(sdk_call(config, environment, [request()], tool="not-an-authorized-tool"))
    assert unknown[0].is_error


def test_recursive_json_is_native_bounded_and_keeps_legacy_array_hashes():
    nested = {"request": {"artifacts": [{"sha256": "a" * 64}], "enabled": True}}
    value = SurfaceCommand.model_validate(request(payload=nested))
    context = AuthenticatedContext("t", "a", "i", "p", "g")
    assert value.to_domain(context).payload == nested
    legacy = SurfaceCommand.model_validate(request(payload={"refs": ("a", "b")}))
    assert legacy.payload["refs"] == ["a", "b"]
    old = legacy.to_domain(context)
    assert old.canonical_hash() == CommandEnvelope.model_validate_json(old.model_dump_json()).canonical_hash()
    too_deep = {}
    for _ in range(34):
        too_deep = {"next": too_deep}
    with pytest.raises(ValueError):
        bounded_payload(too_deep)
    with pytest.raises(ValueError):
        bounded_payload({"value": float("nan")})


def test_enrollment_proof_is_outside_business_envelope_payload():
    context = AuthenticatedContext("t", "a", "i", "node", "grant")
    base = request("runtime.register", target="runtime-1", target_kind="runtime", payload={"request": {
        "provider": "test", "node_id": "node", "node_binding_revision": 1, "producer_grant_ref": "producer",
        "expires_at": (datetime.now(UTC) + timedelta(minutes=1)).isoformat()}})
    first = SurfaceCommand.model_validate(base).to_domain(context)
    complete = base | {"payload": base["payload"] | {"proof": {"challenge_id": "c", "signature": "a" * 128}}}
    assert first == SurfaceCommand.model_validate(complete).to_domain(context)
    assert {"evidence.record", "execution.record", "review.assign", "review.record", "effect.register", "effect.reconcile",
            "node.enroll", "node.rotate", "node.revoke", "node.challenge", "runtime.register", "attempt.register"} <= set(PAYLOADS)


def test_non_loopback_listener_configuration_fails_closed(tmp_path):
    config, environment, secret = profile(tmp_path, extra={"host": "0.0.0.0"})
    with pytest.raises(ValueError):
        SurfaceSettings.model_validate_json(config.read_bytes())
    process = subprocess.run([PYTHON, "-m", "runtime.surface_entry", "--config", str(config), "http"],
                             capture_output=True, env=environment, cwd=SOURCE, timeout=10, check=False)
    assert process.returncode == 2 and secret.encode() not in process.stdout + process.stderr


def test_schema_rejection_is_consistent_across_actual_process_transports(tmp_path):
    config, environment, secret = profile(tmp_path)
    malformed = request() | {"tenant_id": "body-cannot-select-tenant"}
    process, cli_error = cli(config, environment, malformed)
    assert process.returncode == 1 and cli_error["error"]["code"] == "INPUT_INVALID"
    _, _, mcp, _ = asyncio.run(sdk_call(config, environment, [malformed]))
    assert mcp[0].is_error and mcp[0].structured_content["error"] == cli_error["error"]
    with http_process(config, environment) as url:
        result = httpx.post(url + "/v1/commands", json=malformed, headers={"X-ACS-Credential": secret})
        assert result.status_code == 422 and result.json()["error"] == cli_error["error"]


@pytest.fixture
def pg(tmp_path):
    base = os.environ.get("ACS_P1_DSN")
    if not base:
        pytest.skip("ACS_P1_DSN required for real shared-authority surface conformance")
    schema = f"surface_{uuid.uuid4().hex}"
    with psycopg.connect(base, autocommit=True) as admin:
        admin.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
    dsn = make_conninfo(base, options=f"-c search_path={schema}")
    authority = DomainAuthority(dsn)
    try:
        authority.initialize()
        authority.bootstrap_local_grant()
        yield authority, profile(tmp_path, dsn=dsn, context=authority.context)
    finally:
        with psycopg.connect(base, autocommit=True) as admin:
            admin.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))


def test_real_mcp_cli_http_share_pg_identity_and_conflicts(pg):
    authority, (config, environment, secret) = pg
    submitted = request(payload={"scope_id": "local-scope", "agent_slot_id": "local-slot", "source_baseline": "surface-baseline"})
    _, _, mcp, errors = asyncio.run(sdk_call(config, environment, [submitted]))
    first = mcp[0].structured_content
    assert first["ok"] and not mcp[0].is_error
    process, repeated = cli(config, environment, submitted)
    assert process.returncode == 0 and repeated["result"]["duplicate"] is True
    with http_process(config, environment) as url:
        replay = httpx.post(url + "/v1/commands", json=submitted, headers={"X-ACS-Credential": secret}).json()
        assert replay["result"]["operation_id"] == first["result"]["operation_id"] == repeated["result"]["operation_id"]
        changed = submitted | {"payload": submitted["payload"] | {"source_baseline": "changed"}}
        conflict = httpx.post(url + "/v1/commands", json=changed, headers={"X-ACS-Credential": secret})
        assert conflict.status_code == 409 and conflict.json()["error"]["code"] == "IDEMPOTENCY_CONFLICT"
    with authority._connect() as conn:
        for table in ("work_items", "command_dedup", "domain_events", "operations", "outbox"):
            assert conn.execute(sql.SQL("SELECT count(*) FROM {}").format(sql.Identifier(table))).fetchone()[0] == 1
    assert secret not in errors


def test_real_cli_role_is_configured_not_client_supplied(pg, tmp_path):
    authority, _ = pg
    viewer = DomainAuthority(authority._dsn, context=replace(authority.context, principal_ref="surface-viewer", grant_ref="grant:surface-viewer"))
    viewer.bootstrap_local_grant(("work_item.read",))
    config, environment, _ = profile(tmp_path, dsn=authority._dsn, context=viewer.context)
    process, denied = cli(config, environment, request())
    assert process.returncode == 1 and denied["error"]["code"] == "AUTHORIZATION_DENIED"
    process, invalid = cli(config, environment, request() | {"principal_ref": authority.context.principal_ref})
    assert invalid["error"]["code"] == "INPUT_INVALID"
    with authority._connect() as conn:
        assert conn.execute("SELECT count(*) FROM work_items").fetchone()[0] == 0


@pytest.fixture
def evidence_runtime(request):
    # Imported lazily so SDK-only runs do not claim PostgreSQL execution.
    from runtime_tests.test_domain_evidence import runtime
    yield from runtime.__wrapped__(request.getfixturevalue("tmp_path"))


def test_structured_receipt_bundle_review_and_acceptance_across_processes(evidence_runtime, tmp_path):
    f = evidence_runtime
    artifact_settings = {"artifacts": {"root": str(f.store.root), "scope_id": "local-scope"}}
    profiles = {name: profile(tmp_path, dsn=f.dsn, context=getattr(f, name).context, extra=artifact_settings)
                for name in ("node", "engineer", "reviewer", "finalizer")}
    receipt_request = request("execution.record", target="work", payload={"receipt": f.receipt.model_dump(mode="json")})
    signed = f.enrollment.receipt_proof(SurfaceCommand.model_validate(receipt_request).to_domain(f.node.context), f.receipt)
    receipt_request["payload"]["node_proof"] = signed.model_dump(mode="json")
    node_config, node_env, _ = profiles["node"]
    process, receipt = cli(node_config, node_env, receipt_request)
    assert process.returncode == 0 and receipt["ok"]

    evidence_request = request("evidence.record", target="work", payload={
        "evidence": f.evidence.model_dump(mode="json"), "bundle": f.bundle.model_dump(mode="json")})
    engineer_config, engineer_env, _ = profiles["engineer"]
    _, _, submitted, _ = asyncio.run(sdk_call(engineer_config, engineer_env, [evidence_request]))
    assert submitted[0].structured_content["ok"]
    final_config, final_env, final_secret = profiles["finalizer"]
    assignment = request("review.assign", target="work", payload={
        "reviewer_ref": f.reviewer.context.principal_ref, "reviewer_grant_ref": f.reviewer.context.grant_ref})
    assert cli(final_config, final_env, assignment)[1]["ok"]

    reviewer_config, reviewer_env, reviewer_secret = profiles["reviewer"]
    review_request = request("review.record", target="work", payload={"review_id": "surface-review", "verdict": "pass",
        "evidence_ref": f.evidence.evidence_id, "baseline_ref": f.evidence.baseline_ref})
    with http_process(reviewer_config, reviewer_env) as url:
        result = httpx.post(url + "/v1/commands", json=review_request,
                            headers={"X-ACS-Credential": reviewer_secret}).json()
        assert result["ok"]
    transition = {"to_state": "acceptance_ready", "evidence_refs": [f.evidence.evidence_id],
                  "review_ref": "surface-review", "effect_refs": [], "readback_refs": []}
    assert cli(final_config, final_env, request("work_item.transition", target="work", payload=transition))[1]["ok"]
    with http_process(final_config, final_env) as url:
        result = httpx.post(url + "/v1/commands", json=request("work_item.transition", target="work", revision=1,
                            payload=transition | {"to_state": "accepted"}), headers={"X-ACS-Credential": final_secret}).json()
        assert result["ok"] and result["result"]["state"] == "accepted"
    assert f.finalizer.get_work_item("work")["revision"] == 2


def test_enrollment_structured_payload_round_trips_with_surface_signing(pg, tmp_path):
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    from runtime.enrollment import EnrollmentAuthority

    authority, _ = pg
    operator = DomainAuthority(authority._dsn, context=replace(authority.context,
        principal_ref="surface-operator", grant_ref="grant:surface-operator"))
    operator.bootstrap_local_grant(("enrollment.manage",))
    node = DomainAuthority(authority._dsn, context=replace(authority.context,
        principal_ref="surface-node", grant_ref="grant:surface-node"))
    node.bootstrap_local_grant(("runtime.register", "attempt.register", "execution.record"))
    key = Ed25519PrivateKey.generate()
    operator_config, operator_env, _ = profile(tmp_path, dsn=authority._dsn, context=operator.context)
    node_config, node_env, _ = profile(tmp_path, dsn=authority._dsn, context=node.context)
    node_request = request("node.enroll", target="surface-node", target_kind="node", payload={
        "scope_id": "local-scope", "agent_slot_id": "local-slot", "observer_grant_ref": node.context.grant_ref,
        "machine_id": "surface-fixture-machine", "boot_incarnation": "surface-boot-1",
        "public_key": key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw).hex(),
        "expires_at": (datetime.now(UTC) + timedelta(hours=1)).isoformat()})
    assert cli(operator_config, operator_env, node_request)[1]["ok"]
    runtime_request = request("runtime.register", target="surface-runtime", target_kind="runtime", payload={"request": {
        "node_id": "surface-node", "node_binding_revision": 1, "provider": "surface-fixture",
        "producer_grant_ref": authority.context.grant_ref, "expires_at": (datetime.now(UTC) + timedelta(minutes=30)).isoformat()}})
    surface = SurfaceCommand.model_validate(runtime_request)
    envelope = surface.to_domain(node.context)
    challenge_request = request("node.challenge", target="surface-node", target_kind="node", revision=1, payload={
        "purpose": "runtime.register", "purpose_command_id": envelope.command_id,
        "purpose_hash": EnrollmentAuthority.signing_hash(envelope, surface.node_input()), "ttl_seconds": 120})
    challenge = cli(node_config, node_env, challenge_request)[1]
    assert challenge["ok"]
    data = challenge["result"]
    runtime_request["payload"]["proof"] = {"challenge_id": data["challenge_id"],
        "signature": key.sign(bytes.fromhex(data["message_hex"])).hex()}
    _, _, results, _ = asyncio.run(sdk_call(node_config, node_env, [runtime_request]))
    assert results[0].structured_content["ok"]
    assert results[0].structured_content["result"]["binding"]["runtime_id"] == "surface-runtime"


@pytest.fixture
def publication_runtime(evidence_runtime, tmp_path):
    from runtime_tests.test_effect_registration import publication
    yield from publication.__wrapped__(evidence_runtime, tmp_path)


@pytest.mark.parametrize("prepared", [False, True])
def test_effect_registration_and_reconciliation_use_configured_real_gateway(publication_runtime, tmp_path, monkeypatch, prepared):
    from runtime.errors import EffectUnavailable
    from runtime_tests.test_effect_registration import owner_args, write
    p = publication_runtime
    if prepared:
        original = p.writer._record
        def crash(parent, name, body, check, **kwargs):
            if name.endswith(".completed"):
                raise OSError("injected completion loss")
            return original(parent, name, body, check, **kwargs)
        with monkeypatch.context() as injection:
            injection.setattr(p.writer, "_record", crash)
            with pytest.raises(EffectUnavailable):
                write(p)
    else:
        write(p)
    settings = {"artifacts": {"root": str(p.f.store.root), "scope_id": "local-scope"},
                "effects": {"root": str(p.root), "scope_id": "local-scope",
                            "resource_paths": {"publication-resource": "output.txt"}}}
    config, environment, _ = profile(tmp_path, dsn=p.f.dsn, context=p.f.engineer.context, extra=settings)
    registered = cli(config, environment, request("effect.register", target="work", revision=1, payload=p.input))[1]
    assert registered["ok"]
    if prepared:
        p.writer.resume(**owner_args(p.f.engineer, p.lease), relative_path="output.txt", operation_id=p.input["operation_id"])
        _, _, result, _ = asyncio.run(sdk_call(config, environment,
            [request("effect.reconcile", target="work", revision=1, payload={"effect_id": p.input["effect_id"]})]))
        assert result[0].structured_content["ok"]
    with p.f.engineer._connect() as conn:
        assert conn.execute("SELECT status,operation_id FROM effects WHERE effect_id=%s", (p.input["effect_id"],)).fetchone() == (
            "verified", p.input["operation_id"])
