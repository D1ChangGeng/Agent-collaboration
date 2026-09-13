"""Fixed guest adapter for one original OpenCode HostNode operation."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import socket
import stat
import struct
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import psycopg
from psycopg.conninfo import make_conninfo
from temporalio.client import Client

from runtime.delivery import DeliveryService
from runtime.delivery_models import DeliveryPacket
from runtime.domain import DomainAuthority
from runtime.models import CommandEnvelope
from runtime.p1_opencode_host_node import OpenCodeHostRequest, OpenCodeHostResult
from runtime.receiver_paths import (
    PathSecurityRejected,
    open_validated_file,
    private_parent,
)
from tools.runtime.p1_opencode_gate import OpenCodeGateAdmission
from tools.runtime.p1_opencode_gate import MODEL_PROMPT
from tools.runtime.p1_opencode_readback import validate_opencode_lineage

SCENE = "P1-OPENCODE-LIFECYCLE"
SOCKET = Path("/run/acs-p1/opencode-host.sock")
READY = Path("/run/acs-p1/opencode-ready.json")


class OpenCodeProbeRejected(ValueError):
    pass


def _canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def _sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _socket_identity() -> None:
    if os.name != "posix" or not hasattr(socket, "SO_PEERCRED"):
        raise OpenCodeProbeRejected("OpenCode host socket requires POSIX credentials")
    parent = None
    try:
        parent, _ = private_parent(SOCKET.parent)
        info = os.stat(SOCKET.name, dir_fd=parent, follow_symlinks=False)
    except (OSError, PathSecurityRejected) as error:
        raise OpenCodeProbeRejected("OpenCode host socket path is unsafe") from error
    finally:
        if parent is not None:
            os.close(parent)
    if not stat.S_ISSOCK(info.st_mode) or info.st_uid != os.geteuid():
        raise OpenCodeProbeRejected("OpenCode host socket inode differs")


def _connect() -> socket.socket:
    _socket_identity()
    peer = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        peer.settimeout(5)
        peer.connect(str(SOCKET))
        _pid, uid, _gid = struct.unpack(
            "3i", peer.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12)
        )
        if uid != os.geteuid():
            raise OpenCodeProbeRejected("OpenCode host socket peer UID differs")
        return peer
    except BaseException:
        peer.close()
        raise


def dispatch_without_ack(request: OpenCodeHostRequest) -> None:
    if request.action != "dispatch":
        raise OpenCodeProbeRejected("OpenCode ACK-loss requires original dispatch")
    try:
        with _connect() as peer:
            peer.sendall(request.model_dump_json().encode() + b"\n")
            peer.shutdown(socket.SHUT_RDWR)
    except OSError as error:
        raise OpenCodeProbeRejected("OpenCode original request send is unverified") from error


def host_readback(
    request: OpenCodeHostRequest, identity: dict[str, str], *, timeout: float = 5.0
) -> OpenCodeHostResult:
    if request.action != "readback" or not 0 < timeout <= 120:
        raise OpenCodeProbeRejected("OpenCode host readback is outside fixed boundary")
    try:
        with _connect() as peer:
            deadline = time.monotonic() + timeout
            peer.sendall(request.model_dump_json().encode() + b"\n")
            frame = bytearray()
            while len(frame) <= 262144 and not frame.endswith(b"\n"):
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise OpenCodeProbeRejected("OpenCode host readback deadline expired")
                peer.settimeout(remaining)
                block = peer.recv(min(8192, 262145 - len(frame)))
                if not block:
                    break
                frame.extend(block)
    except OSError as error:
        raise OpenCodeProbeRejected("OpenCode host original readback is unavailable") from error
    if len(frame) > 262144 or not frame.endswith(b"\n") or frame.count(b"\n") != 1:
        raise OpenCodeProbeRejected("OpenCode host response frame differs")
    try:
        result = OpenCodeHostResult.model_validate_json(frame[:-1], strict=True)
    except ValueError as error:
        raise OpenCodeProbeRejected("OpenCode host response schema differs") from error
    if (
        result.status != "delivered"
        or any(getattr(result, key) != value for key, value in identity.items())
    ):
        raise OpenCodeProbeRejected("OpenCode host response left original delivery")
    return result


def _admission_and_ready(
    profile: dict[str, Any], commit: str, tree: str, run_id: str
) -> tuple[OpenCodeGateAdmission, dict[str, Any]]:
    if (
        Path(os.environ.get("ACS_GATE_OPENCODE_PROFILE", ""))
        != Path("/run/acs-p1/opencode-profile.json")
        or Path(os.environ.get("ACS_GATE_OPENCODE_BUDGET", ""))
        != Path("/run/acs-p1/opencode-budget.json")
        or Path(os.environ.get("ACS_GATE_OPENCODE_HOST_READY", "")) != READY
        or Path(os.environ.get("ACS_GATE_OPENCODE_HOST_SOCKET", "")) != SOCKET
    ):
        raise OpenCodeProbeRejected("restricted OpenCode mounts are unavailable")
    scene_sha = os.environ.get("ACS_GATE_OPENCODE_PROFILE_SHA256", "")
    budget_sha = os.environ.get("ACS_GATE_OPENCODE_BUDGET_SHA256", "")
    ready_sha = os.environ.get("ACS_GATE_OPENCODE_HOST_READY_SHA256", "")
    if not all(re.fullmatch(r"[a-f0-9]{64}", value) for value in (
        scene_sha, budget_sha, ready_sha
    )):
        raise OpenCodeProbeRejected("OpenCode owner pin is missing")
    admission = OpenCodeGateAdmission.load(
        Path("/run/acs-p1/opencode-profile.json"), scene_sha,
        Path("/run/acs-p1/opencode-budget.json"), budget_sha,
        source_commit=commit, source_tree=tree,
    ).bind_run(run_id, os.environ.get("ACS_GATE_MACHINE_ID", ""), profile["node_id"])
    descriptor, _ = open_validated_file(READY, private=True)
    try:
        payload = os.read(descriptor, 65537)
    finally:
        os.close(descriptor)
    if len(payload) > 65536 or _sha(payload) != ready_sha:
        raise OpenCodeProbeRejected("OpenCode ready file digest differs")
    try:
        ready = json.loads(payload)
    except (UnicodeError, ValueError) as error:
        raise OpenCodeProbeRejected("OpenCode ready file is malformed") from error
    required = {
        "schema_version", "run_id", "schema", "endpoint_id", "endpoint_descriptor",
        "binding_revision", "node_id", "machine_id", "boot_incarnation",
        "source_commit", "source_tree", "scene_sha256", "budget_sha256",
        "config_sha256", "native_sha256", "deadline",
    }
    suffix = run_id.removeprefix("p1-run-")[:24]
    if (
        not isinstance(ready, dict) or set(ready) != required
        or ready["schema_version"] != "acs-p1-opencode-host-ready/1"
        or ready["run_id"] != run_id
        or ready["schema"] != "p1_opencode_" + suffix
        or ready["endpoint_id"] != "opencode-endpoint-" + suffix
        or ready["binding_revision"] != 1
        or ready["node_id"] != profile["node_id"]
        or ready["machine_id"] != admission.machine_id
        or ready["source_commit"] != commit or ready["source_tree"] != tree
        or ready["scene_sha256"] != scene_sha
        or ready["budget_sha256"] != budget_sha
        or ready["config_sha256"] != admission.scene["config_sha256"]
        or ready["native_sha256"] != admission.scene["native_executable_sha256"]
        or not isinstance(ready["endpoint_descriptor"], dict)
        or ready["endpoint_descriptor"].get("supports_invoke") is not True
        or ready["endpoint_descriptor"].get("evidence_class") != "native_driver_observation"
        or any(ready["endpoint_descriptor"].get(name) != ready[name] for name in (
            "machine_id", "node_id", "boot_incarnation"
        ))
    ):
        raise OpenCodeProbeRejected("OpenCode host ready identity differs")
    deadline = datetime.fromisoformat(ready["deadline"])
    if deadline.tzinfo is None or deadline <= datetime.now(UTC) + timedelta(seconds=1):
        raise OpenCodeProbeRejected("OpenCode host deadline expired")
    return admission, ready


def run_scene(
    profile: dict[str, Any], ledger: Any, commit: str, tree: str,
    run_id: str, suffix: str, issued_at: datetime,
) -> dict[str, Any]:
    from tools.runtime.p1_profile_probe import _private_json

    admission, ready = _admission_and_ready(profile, commit, tree, run_id)
    ledger.reserve_schema(ready["schema"])
    scoped = make_conninfo(profile["postgres_dsn"], options=f"-c search_path={ready['schema']}")
    authority = DomainAuthority(scoped)
    work_id = "opencode-work-" + suffix
    message_id = "opencode-message-" + suffix
    deadline = datetime.fromisoformat(ready["deadline"])

    def command(name: str, target_kind: str, target_id: str) -> CommandEnvelope:
        return CommandEnvelope(
            command_id=f"p1-opencode:{suffix}:{name}",
            idempotency_key=f"p1-opencode:{suffix}:{name}:key",
            correlation_id=run_id, command_type=name,
            tenant_id=authority.tenant_id,
            authority_id=authority.context.authority_id,
            authority_incarnation=authority.context.authority_incarnation,
            principal_ref=authority.context.principal_ref,
            grant_ref=authority.context.grant_ref,
            target_kind=target_kind, target_id=target_id, expected_revision=0,
            issued_at=issued_at, deadline=deadline,
        )

    authority.create_work_item(
        command("work_item.create", "work_item", work_id),
        "local-scope", "local-slot", commit,
    )
    packet = DeliveryPacket(
        work_item_id=work_id, target_scope_id="local-scope",
        target_agent_slot_id="local-slot", accepted_revision=0,
        goal="Observe one authorized OpenCode lifecycle prompt",
        accepted_state_summary="revision zero",
        request=MODEL_PROMPT,
        source_baseline=commit, expected_response="ACS_P1_OPENCODE_API_OK",
        activation="invoke", deadline=deadline - timedelta(seconds=1),
        maximum_attempts=1,
    )
    send = command("message.send", "message", message_id)
    sent = DeliveryService(authority, {}).send_message(
        send, packet, endpoint_id=ready["endpoint_id"], binding_revision=1,
    )
    request = OpenCodeHostRequest(
        action="dispatch", run_id=run_id, tenant_id=authority.tenant_id,
        message_id=message_id, command_id=send.command_id,
        operation_id=sent.operation_id, endpoint_id=ready["endpoint_id"],
        source_commit=commit,
        native_sha256=admission.scene["native_executable_sha256"],
        config_sha256=ready["config_sha256"],
    )
    dispatch_without_ack(request)
    read_request = request.model_copy(update={"action": "readback"})
    identity = {
        "run_id": run_id, "tenant_id": authority.tenant_id,
        "message_id": message_id, "command_id": send.command_id,
        "operation_id": sent.operation_id,
    }
    # One read-only collection waits behind the original dispatch on the host.
    # A timeout is uncertain; there is no second native activation or socket flood.
    result = host_readback(read_request, identity, timeout=120)
    if result.scene_readback is None:
        raise OpenCodeProbeRejected("OpenCode original attempt has no final readback")
    lineage = admission.assert_final_lineage(result.scene_readback)
    if (
        result.scene_readback_sha256 != _sha(_canonical(lineage))
        or lineage["command_id"] != send.command_id
        or lineage["message_id"] != message_id
        or lineage["operation_id"] != sent.operation_id
        or lineage["attempt_id"] != result.attempt_id
        or lineage["dispatch_id"] != result.dispatch_id
    ):
        raise OpenCodeProbeRejected("OpenCode final attempt identity differs")
    raw = ledger.root / (SCENE + "-runtime.json")
    data = _private_json(raw, lineage)
    with authority._connect() as connection:
        events = connection.execute(
            "SELECT event_id FROM domain_events WHERE tenant_id=%s AND command_id=%s",
            (authority.tenant_id, send.command_id),
        ).fetchall()
        receipts = connection.execute(
            "SELECT receipt_id FROM delivery_receipts WHERE tenant_id=%s AND message_id=%s "
            "AND layer='response_received'", (authority.tenant_id, message_id),
        ).fetchall()
    if len(events) != 1 or len(receipts) != 1:
        raise OpenCodeProbeRejected("OpenCode Domain event/response receipt is incomplete")
    row = {
        "scenario_id": SCENE, "run_id": run_id,
        "operation_id": sent.operation_id, "message_id": message_id,
        "event_id": str(events[0][0]), "receipt_id": receipts[0][0],
        "test_digest": _sha(data), "raw_path": raw.name,
        "pg_schema": ready["schema"],
        "temporal_workflow_id": lineage["temporal"]["workflow_id"],
        "temporal_run_id": lineage["temporal"]["run_id"],
        "lineage_json": json.dumps(lineage, sort_keys=True),
        "source_commit": commit, "source_tree": tree,
        "status": "passed", "created_at": datetime.now(UTC).isoformat(),
    }
    ledger.put_opencode_request(SCENE, read_request.model_dump_json())
    ledger.put_opencode_fault(SCENE, {
        "schema_version": "acs-p1-opencode-ack-loss/1",
        "run_id": run_id, "command_id": send.command_id,
        "message_id": message_id, "operation_id": sent.operation_id,
        "dispatch_request_sha256": _sha(request.model_dump_json().encode()),
        "closed_without_reply": True,
        "readback_request_sha256": _sha(read_request.model_dump_json().encode()),
        "readback_sha256": result.scene_readback_sha256,
        "native_prompt_async_count": lineage["driver"]["prompt_async_count"],
    })
    ledger.put(row)
    return row


def read_layer(
    profile: dict[str, Any], ledger: Any, row: dict[str, Any], kind: str,
) -> dict[str, Any]:
    if kind not in {"command_output", "postgresql", "sqlite", "temporal", "driver", "os"}:
        raise OpenCodeProbeRejected("unknown OpenCode authority layer")
    lineage = validate_opencode_lineage(json.loads(row["lineage_json"]))
    if kind == "command_output":
        raw = ledger.root / row["raw_path"]
        descriptor, _ = open_validated_file(raw, private=True)
        try:
            data = os.read(descriptor, 262145)
        finally:
            os.close(descriptor)
        fault = ledger.opencode_fault(SCENE)
        request = OpenCodeHostRequest.model_validate_json(ledger.opencode_request(SCENE), strict=True)
        dispatch = request.model_copy(update={"action": "dispatch"})
        if (
            len(data) > 262144 or _sha(data) != row["test_digest"]
            or json.loads(data) != lineage
            or fault.get("schema_version") != "acs-p1-opencode-ack-loss/1"
            or fault.get("run_id") != lineage["run_id"]
            or fault.get("command_id") != lineage["command_id"]
            or fault.get("message_id") != lineage["message_id"]
            or fault.get("operation_id") != lineage["operation_id"]
            or fault.get("dispatch_request_sha256") != _sha(dispatch.model_dump_json().encode())
            or fault.get("readback_request_sha256") != _sha(request.model_dump_json().encode())
            or fault.get("readback_sha256") != _sha(_canonical(lineage))
            or fault.get("closed_without_reply") is not True
            or fault.get("native_prompt_async_count") != 1
        ):
            raise OpenCodeProbeRejected("OpenCode original ACK-loss evidence differs")
        return {"command_output": True, "ack_loss_injected": True,
                "lineage_sha256": _sha(_canonical(lineage))}
    if kind == "postgresql":
        scoped = make_conninfo(profile["postgres_dsn"], options=f"-c search_path={row['pg_schema']}")
        with psycopg.connect(scoped) as connection:
            message = connection.execute(
                "SELECT command_id,operation_id,state,receipt_high_water FROM delivery_messages "
                "WHERE message_id=%s", (lineage["message_id"],),
            ).fetchone()
            attempts = connection.execute(
                "SELECT attempt_id,dispatch_id,status,selection_json->>'machine_id',"
                "selection_json->>'node_id' FROM delivery_attempts WHERE message_id=%s ORDER BY ordinal",
                (lineage["message_id"],),
            ).fetchall()
            projections = connection.execute(
                "SELECT projection_id,invocation_id,attempt_id,dispatch_id,response_digest,disposition "
                "FROM native_response_observations WHERE message_id=%s",
                (lineage["message_id"],),
            ).fetchall()
            receipts = connection.execute(
                "SELECT receipt_id,layer,attempt_id,dispatch_id FROM delivery_receipts "
                "WHERE message_id=%s AND layer IN ('runtime_dispatched','response_received')",
                (lineage["message_id"],),
            ).fetchall()
            provider = connection.execute(
                "SELECT provider_workflow_id,provider_run_id FROM operations WHERE operation_id=%s",
                (lineage["operation_id"],),
            ).fetchone()
        identity = (lineage["attempt_id"], lineage["dispatch_id"])
        if (
            message != (lineage["command_id"], lineage["operation_id"], "delivered", "response_received")
            or attempts != [(lineage["attempt_id"], lineage["dispatch_id"], "delivered",
                             lineage["machine_id"], lineage["node_id"])]
            or projections != [(lineage["response"]["projection_id"], lineage["invocation_id"],
                                lineage["attempt_id"], lineage["dispatch_id"],
                                lineage["response"]["response_digest"], "applied")]
            or {layer: (attempt, dispatch) for _receipt, layer, attempt, dispatch in receipts}
            != {"runtime_dispatched": identity, "response_received": identity}
            or len(receipts) != 2
            or provider != (lineage["temporal"]["workflow_id"], lineage["temporal"]["run_id"])
        ):
            raise OpenCodeProbeRejected("OpenCode PostgreSQL authority changed")
        return {"postgresql_readback": True, "receipt_ids": sorted(item[0] for item in receipts)}
    if kind == "temporal":
        async def observe() -> object:
            client = await Client.connect(
                profile["temporal_endpoint"], namespace=profile["temporal_namespace"]
            )
            handle = client.get_workflow_handle(
                lineage["temporal"]["workflow_id"], run_id=lineage["temporal"]["run_id"]
            )
            return await handle.result()
        observed = asyncio.run(observe())
        if not isinstance(observed, dict) or observed.get("status") != "delivered":
            raise OpenCodeProbeRejected("OpenCode original Temporal Workflow/Run changed")
        return {"temporal_readback": True, "run_id": lineage["temporal"]["run_id"]}
    request = OpenCodeHostRequest.model_validate_json(ledger.opencode_request(SCENE), strict=True)
    if (
        request.action != "readback"
        or request.run_id != lineage["run_id"]
        or request.message_id != lineage["message_id"]
        or request.command_id != lineage["command_id"]
        or request.operation_id != lineage["operation_id"]
        or request.source_commit != lineage["source_commit"]
    ):
        raise OpenCodeProbeRejected("OpenCode host readback request changed")
    observed = host_readback(request, {
        "run_id": lineage["run_id"], "tenant_id": request.tenant_id,
        "message_id": lineage["message_id"], "command_id": lineage["command_id"],
        "operation_id": lineage["operation_id"],
    })
    if (
        observed.scene_readback != lineage
        or observed.scene_readback_sha256 != _sha(_canonical(lineage))
        or observed.attempt_id != lineage["attempt_id"]
        or observed.dispatch_id != lineage["dispatch_id"]
    ):
        raise OpenCodeProbeRejected("OpenCode host fresh six-layer readback changed")
    if kind == "sqlite":
        return {"sqlite_readback": True, "node_state_sha256": _sha(_canonical(lineage["node"]))}
    if kind == "driver":
        return {"driver_readback": True, "artifact_sha256": lineage["response"]["response_digest"]}
    proof = observed.os_observation
    if not isinstance(proof, dict) or proof != lineage["os"]:
        raise OpenCodeProbeRejected("OpenCode host OS termination proof changed")
    return {"os_readback": True, "unit_inactive": True,
            "containment_id": proof["containment_id"]}
