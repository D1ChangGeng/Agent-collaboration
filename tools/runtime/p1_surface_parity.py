"""Exercise one Domain command through real MCP, CLI and loopback HTTP surfaces.

This component does not register a formal P1 Gate scene. A Gate plan must first
declare and bind the additional loopback HTTP listener used by this probe.
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
from contextlib import contextmanager
from dataclasses import asdict, replace
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import httpx

from runtime.domain import DomainAuthority
from runtime.surfaces import SurfaceCommand


class SurfaceParityRejected(RuntimeError):
    pass


def _private(path: Path, data: bytes) -> None:
    descriptor = os.open(
        path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
        0o600,
    )
    try:
        while data:
            written = os.write(descriptor, data)
            if written <= 0:
                raise SurfaceParityRejected("private surface file write stalled")
            data = data[written:]
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _child_env(source_root: Path, private_home: Path) -> dict[str, str]:
    return {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": str(private_home),
        "PYTHONPATH": str(source_root),
        "PYTHONDONTWRITEBYTECODE": "1",
        "LC_ALL": "C.UTF-8",
    }


def _process_args(config: Path, transport: str) -> list[str]:
    return [sys.executable, "-m", "runtime.surface_entry", "--config", str(config), transport]


async def _mcp(config: Path, environment: dict[str, str], source_root: Path,
               command: dict[str, Any]) -> tuple[dict[str, Any], bytes]:
    try:
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client
    except ImportError as error:
        raise SurfaceParityRejected("MCP runtime is unavailable") from error
    parameters = StdioServerParameters(
        command=sys.executable, args=_process_args(config, "mcp")[1:],
        env=environment, cwd=str(source_root),
    )
    with tempfile.TemporaryFile(mode="w+", encoding="utf-8", dir=config.parent) as errors:
        async with stdio_client(parameters, errlog=errors) as streams, ClientSession(
            *streams, read_timeout_seconds=15,
        ) as session:
            await session.initialize()
            inventory = await session.list_tools()
            if not inventory.tools or inventory.tools[0].name != "run":
                raise SurfaceParityRejected("MCP tool inventory changed")
            result = await session.call_tool("run", {"request": command})
        errors.seek(0)
        stderr = errors.read().encode()
    if result.is_error or not isinstance(result.structured_content, dict):
        raise SurfaceParityRejected("MCP rejected the original Domain command")
    return result.structured_content, stderr


@contextmanager
def _http(config: Path, environment: dict[str, str], source_root: Path,
          streams: dict[str, bytes]):
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    body = json.loads(config.read_bytes())
    body["port"] = port
    config.write_text(json.dumps(body, sort_keys=True), encoding="utf-8")
    process = subprocess.Popen(
        _process_args(config, "http"), cwd=source_root, env=environment,
        stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    url = f"http://127.0.0.1:{port}"
    try:
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise SurfaceParityRejected("HTTP surface exited before readiness")
            try:
                if httpx.get(url + "/v1/health", timeout=0.3).status_code == 200:
                    break
            except httpx.HTTPError:
                pass
            time.sleep(0.02)
        else:
            raise SurfaceParityRejected("HTTP surface readiness timed out")
        yield url
    finally:
        if process.poll() is None:
            process.terminate()
        try:
            output, errors = process.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            output, errors = process.communicate(timeout=5)
        # The caller checks these bytes before recording a proof. Nothing is
        # copied into Gate evidence.
        streams["bytes"] = output + errors


def exercise(
    authority: DomainAuthority, *, source_root: Path, work_item_id: str,
    source_baseline: str, command_id: str, idempotency_key: str,
    issued_at: datetime,
) -> dict[str, Any]:
    """Create one WorkItem by MCP, replay it by CLI/HTTP, then verify PG identity."""
    if os.name != "posix" or not source_root.is_absolute() or not issued_at.tzinfo:
        raise SurfaceParityRejected("Surface parity requires a pinned POSIX source and time")
    token = secrets.token_urlsafe(32)
    with tempfile.TemporaryDirectory(prefix="acs-p1-surface-", dir="/tmp") as temporary:
        private = Path(temporary)
        if private.stat().st_mode & 0o777 != 0o700:
            raise SurfaceParityRejected("surface private directory is not owner-only")
        dsn_file, token_file, config = (
            private / "dsn", private / "credential", private / "surface.json",
        )
        _private(dsn_file, authority._dsn.encode() + b"\n")
        _private(token_file, token.encode() + b"\n")
        context = replace(
            authority.context, credential_hash=hashlib.sha256(token.encode()).hexdigest(),
        )
        _private(config, json.dumps({
            "schema_version": "acs-surfaces/1", "context": asdict(context),
            "dsn_ref": {"kind": "file", "name": str(dsn_file)},
            "credential_ref": {"kind": "file", "name": str(token_file)},
        }, sort_keys=True).encode())
        environment = _child_env(source_root, private)
        command = SurfaceCommand(
            command_type="work_item.create", target_kind="work_item",
            target_id=work_item_id, expected_revision=0, command_id=command_id,
            idempotency_key=idempotency_key, correlation_id=command_id,
            issued_at=issued_at, deadline=issued_at + timedelta(minutes=30),
            payload={"scope_id": "local-scope", "agent_slot_id": "local-slot",
                     "source_baseline": source_baseline},
        ).model_dump(mode="json")
        first, mcp_errors = asyncio.run(_mcp(config, environment, source_root, command))
        cli = subprocess.run(
            _process_args(config, "cli"), input=json.dumps(command).encode(),
            cwd=source_root, env=environment, capture_output=True, timeout=20, check=False,
        )
        try:
            second = json.loads(cli.stdout)
        except (ValueError, UnicodeError) as error:
            raise SurfaceParityRejected("CLI did not return structured readback") from error
        http_streams: dict[str, bytes] = {}
        with _http(config, environment, source_root, http_streams) as url:
            replay = httpx.post(
                url + "/v1/commands", json=command,
                headers={"X-ACS-Credential": token}, timeout=10,
            )
            changed = dict(command)
            changed["payload"] = dict(command["payload"], source_baseline="changed")
            conflict = httpx.post(
                url + "/v1/commands", json=changed,
                headers={"X-ACS-Credential": token}, timeout=10,
            )
        secret_bytes = (token.encode(), authority._dsn.encode())
        outputs = (
            mcp_errors, cli.stdout, cli.stderr, replay.content,
            conflict.content, http_streams.get("bytes", b""),
        )
        if any(secret in output for secret in secret_bytes for output in outputs):
            raise SurfaceParityRejected("surface output contained a private reference")
        third = replay.json()
        denied = conflict.json()
        if (
            cli.returncode != 0 or replay.status_code != 200
            or conflict.status_code != 409 or not first.get("ok")
            or not second.get("ok") or not third.get("ok")
            or second.get("result", {}).get("duplicate") is not True
            or third.get("result", {}).get("duplicate") is not True
            or denied.get("error", {}).get("code") != "IDEMPOTENCY_CONFLICT"
        ):
            raise SurfaceParityRejected("MCP/CLI/HTTP surface disposition differs")
        operation_ids = [
            value["result"]["operation_id"] for value in (first, second, third)
        ]
        if len(set(operation_ids)) != 1:
            raise SurfaceParityRejected("surface replays changed the Domain operation")
        operation_id = operation_ids[0]
        with authority._connect() as connection:
            work = connection.execute(
                "SELECT scope_id,agent_slot_id,source_baseline,state,revision "
                "FROM work_items WHERE work_item_id=%s", (work_item_id,),
            ).fetchone()
            dedup = connection.execute(
                "SELECT count(*) FROM command_dedup WHERE command_id=%s", (command_id,),
            ).fetchone()[0]
            events = connection.execute(
                "SELECT count(*) FROM domain_events WHERE command_id=%s", (command_id,),
            ).fetchone()[0]
            operations = connection.execute(
                "SELECT count(*) FROM operations WHERE operation_id=%s", (operation_id,),
            ).fetchone()[0]
            outbox = connection.execute(
                "SELECT count(*) FROM outbox WHERE operation_id=%s", (operation_id,),
            ).fetchone()[0]
        if (
            work != ("local-scope", "local-slot", source_baseline, "candidate", 0)
            or (dedup, events, operations, outbox) != (1, 1, 1, 1)
        ):
            raise SurfaceParityRejected("shared PostgreSQL operation differs from surfaces")
        return {
            "work_item_id": work_item_id, "command_id": command_id,
            "operation_id": operation_id, "source_baseline": source_baseline,
            "mcp_created": True, "cli_exact_replay": True,
            "http_exact_replay": True, "http_conflict_rejected": True,
            "domain_row_count": 1, "active_http_processes": 0,
        }
