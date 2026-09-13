"""Cross-authority checks for one P1 Codex lifecycle probe.

The probe reads Domain and Temporal directly and obtains Node, Driver and OS
readbacks through the restricted host endpoint. This module admits their
result only when they describe one original native turn.
It never starts a Codex turn or reads a provider credential.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import socket
import sqlite3
import stat
import struct
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import urlsplit

import psycopg
from psycopg.conninfo import make_conninfo
from temporalio.client import Client

from runtime.artifacts import LocalArtifactStore
from runtime.codex_driver import (
    CodexAppServerDriver,
    OutcomeUncertain,
)
from runtime.delivery_models import InvocationRequest
from runtime.node import NodeJournal
from runtime.p1_codex_host_node import CodexHostRequest, CodexHostResult
from runtime.receiver_paths import (
    PathSecurityRejected,
    open_validated_file,
    private_parent,
)
from runtime.recovery import AuthoritySnapshot, PostgresDelayedResponseAuthority
from runtime.recovery_models import BoundaryRejected
from runtime.response_collector import NativeResponseCollector, artifact_response_store


class CodexSceneRejected(ValueError):
    """An observed layer cannot prove the bounded native lifecycle."""


def _text(value: object, name: str) -> str:
    if not isinstance(value, str) or not 1 <= len(value) <= 256:
        raise CodexSceneRejected(f"{name} is missing or outside bound")
    return value


def _sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _file_sha(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            value.update(chunk)
    return value.hexdigest()


def _canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def native_usage_observation(
    events: list[tuple[str, dict[str, Any]]], thread_id: str, turn_id: str
) -> dict[str, Any]:
    """Preserve the original turn's token notification, or its observed absence."""
    matching = []
    for kind, body in events:
        if kind != "native_event" or body.get("kind") != "notification":
            continue
        message = body.get("message")
        if not isinstance(message, dict) or message.get("method") != "thread/tokenUsage/updated":
            continue
        params = message.get("params")
        if (
            isinstance(params, dict)
            and params.get("threadId") == thread_id
            and params.get("turnId") == turn_id
        ):
            if not isinstance(params.get("tokenUsage"), dict):
                raise CodexSceneRejected("native token usage shape differs")
            matching.append(params)
    if not matching:
        return {"status": "not_observed", "notification_count": 0}
    latest = matching[-1]
    usage = latest["tokenUsage"]
    required = {
        "cachedInputTokens", "inputTokens", "outputTokens", "reasoningOutputTokens", "totalTokens"
    }
    for part in ("last", "total"):
        value = usage.get(part)
        if not isinstance(value, dict) or not required <= set(value):
            raise CodexSceneRejected("native token usage shape differs")
        if any(type(value[name]) is not int or value[name] < 0 for name in required):
            raise CodexSceneRejected("native token usage counts differ")
    return {
        "status": "observed",
        "notification_count": len(matching),
        "last": usage["last"],
        "total": usage["total"],
        "native_notification_sha256": _sha(_canonical(latest)),
    }


def _valid_token_counts(value: object) -> bool:
    required = {
        "cachedInputTokens", "inputTokens", "outputTokens", "reasoningOutputTokens", "totalTokens"
    }
    return (
        isinstance(value, dict)
        and required <= set(value)
        and all(type(value[name]) is int and value[name] >= 0 for name in required)
    )


def _count(value: object, expected: int) -> bool:
    return type(value) is int and value == expected


SCENE_PROFILE_FIELDS = frozenset(
    {
        "schema_version",
        "native_executable_path",
        "native_executable_sha256",
        "native_executable_size",
        "codex_version",
        "schema_sha256",
        "provider_alias",
        "provider_url",
        "wire_api",
        "auth_command",
        "auth_key_ref_path",
        "auth_key_ref_path_sha256",
        "model",
        "reasoning_effort",
        "model_catalog_entry",
        "model_catalog_path",
        "model_catalog_sha256",
        "model_catalog_size",
        "max_turn_starts",
        "max_collect_reads",
        "max_elapsed_seconds",
        "budget_evidence_ref",
    }
)
CODEX_SCHEMA = Path("/mnt/runtime_tests/schema-0.153.2/codex_app_server_protocol.schemas.json")
MODEL_PROMPT = "Reply with exactly ACS_P1_CODEX_API_OK. Do not call tools."
DECISION_ID = "P1-CODEX-LIFECYCLE-ONE-TURN-01"


def verify_budget_decision(
    path: Path,
    expected_sha256: str,
    *,
    source_commit: str,
    source_tree: str,
    scene_profile_sha256: str,
    decision_id: str,
    provider_alias: str,
    model: str,
) -> dict[str, Any]:
    """Read the owner-only, digest-pinned decision before native mutation."""
    if os.name != "posix" or not path.is_absolute():
        raise CodexSceneRejected("one-turn budget decision requires an absolute POSIX path")
    _private_directory(path.parent)
    data = _private_file(path)
    if not re.fullmatch(r"[0-9a-f]{64}", expected_sha256) or _sha(data) != expected_sha256:
        raise CodexSceneRejected("Management one-turn budget file digest differs")
    try:
        value = json.loads(data)
    except (UnicodeError, ValueError):
        raise CodexSceneRejected("Management one-turn budget is malformed") from None
    if (
        not isinstance(value, dict)
        or value.get("schema_version") != "acs-p1-model-request-budget/1"
        or decision_id != DECISION_ID
        or value.get("decision_id") != decision_id
        or value.get("source_commit") != source_commit
        or value.get("source_tree") != source_tree
        or value.get("scene_profile_sha256") != scene_profile_sha256
        or value.get("scenario_id") != "P1-CODEX-LIFECYCLE"
        or value.get("provider_alias") != provider_alias
        or value.get("model") != model
        or value.get("reasoning_effort") != "low"
        or value.get("prompt") != MODEL_PROMPT
        or not _count(value.get("max_turn_starts"), 1)
        or not _count(value.get("max_collect_reads"), 6)
        or not _count(value.get("max_elapsed_seconds"), 120)
        or "No second turn/start" not in value.get("retry_policy", "")
        or "monetary cap not observed" not in value.get("spend_status", "")
        or "No tool invocation" not in value.get("tool_policy", "")
    ):
        raise CodexSceneRejected("Management one-turn budget content differs")
    return {"decision_sha256": expected_sha256, "monetary_cap": "unknown"}


def validate_scene_profile(value: object) -> dict[str, Any]:
    """Validate public references only; the runner attests hidden host files."""
    if not isinstance(value, dict) or set(value) != SCENE_PROFILE_FIELDS:
        raise CodexSceneRejected("Codex scene profile fields differ")
    if value["schema_version"] != "acs-p1-codex-scene/1":
        raise CodexSceneRejected("Codex scene profile schema differs")
    provider_url = value["provider_url"]
    if (
        not isinstance(provider_url, str)
        or len(provider_url) > 2048
        or any(ord(character) < 32 for character in provider_url)
    ):
        raise CodexSceneRejected("Codex provider URL is not bounded")
    try:
        parsed_url = urlsplit(provider_url)
        port = parsed_url.port
    except ValueError as error:
        raise CodexSceneRejected("Codex provider URL is malformed") from error
    if (
        value["codex_version"] != "0.153.2"
        or not isinstance(value["provider_alias"], str)
        or not re.fullmatch(r"[a-z][a-z0-9_-]{1,63}", value["provider_alias"])
        or parsed_url.scheme != "https"
        or not parsed_url.hostname
        or not re.fullmatch(r"[A-Za-z0-9.-]{1,253}", parsed_url.hostname)
        or port is not None and not 1 <= port <= 65535
        or parsed_url.username is not None
        or parsed_url.password is not None
        or parsed_url.query
        or parsed_url.fragment
        or not parsed_url.path.startswith("/")
        or value["wire_api"] != "responses"
        or value["auth_command"] != "/usr/bin/cat"
        or value["reasoning_effort"] != "low"
    ):
        raise CodexSceneRejected("Codex provider or strict model profile differs")
    for field in (
    for field in ("native_executable_path", "model_catalog_path", "auth_key_ref_path"):
        path = value[field]
        if (
            not isinstance(path, str)
            or not PurePosixPath(path).is_absolute()
            or ".." in PurePosixPath(path).parts
            or any(ord(char) < 32 for char in path)
        ):
            raise CodexSceneRejected(f"{field} is not a bounded absolute host reference")
    if (
        type(value["native_executable_size"]) is not int
        or not 1_000_000 <= value["native_executable_size"] <= 500_000_000
        or type(value["model_catalog_size"]) is not int
        or not 1_000 <= value["model_catalog_size"] <= 100_000
        or value["auth_key_ref_path_sha256"] != _sha(value["auth_key_ref_path"].encode())
        or any(
            not isinstance(value[field], str) or not re.fullmatch("[0-9a-f]{64}", value[field])
            for field in (
                "native_executable_sha256", "model_catalog_sha256", "schema_sha256",
            )
        )
    ):
        raise CodexSceneRejected("Codex executable, schema or key reference pin differs")
    model = value["model"]
    entry = value["model_catalog_entry"]
    if (
        not isinstance(model, str)
        or not re.fullmatch(r"[a-z0-9][a-z0-9.-]{1,127}", model)
        or not isinstance(entry, dict)
        or entry.get("slug") != model
        or entry.get("experimental_supported_tools") != []
        or len(_canonical(entry)) > 100_000
        or re.search(rb"(?i)(password|secret|api[_-]?key|access[_-]?token)", _canonical(entry))
    ):
        raise CodexSceneRejected("reviewed model catalog entry is not tool-free and exact")
    if value["budget_evidence_ref"] != DECISION_ID:
        raise CodexSceneRejected("request budget evidence reference is missing")
    TurnBudget(
        value["max_turn_starts"],
        value["max_collect_reads"],
        value["max_elapsed_seconds"],
    )
    return value


def _private_directory(path: Path) -> None:
    try:
        descriptor, _ = private_parent(path)
    except (OSError, PathSecurityRejected) as error:
        raise CodexSceneRejected("Codex capacity directory is not owner 0700") from error
    os.close(descriptor)


def _private_file(path: Path) -> bytes:
    try:
        descriptor, _ = open_validated_file(path, private=True)
    except (OSError, PathSecurityRejected) as error:
        raise CodexSceneRejected("Codex profile file is not owner 0600") from error
    try:
        info = os.fstat(descriptor)
        if info.st_size > 100_000:
            raise CodexSceneRejected("Codex profile file is not owner 0600 single-link")
        return os.read(descriptor, 100_001)
    finally:
        os.close(descriptor)


def load_scene_profile(path: Path, expected_sha256: str) -> dict[str, Any]:
    if os.name != "posix" or path != Path("/run/acs-p1/codex-profile.json"):
        raise CodexSceneRejected("Codex scene requires the fixed sandbox profile mount")
    _private_directory(path.parent)
    data = _private_file(path)
    if _sha(data) != expected_sha256:
        raise CodexSceneRejected("Codex scene profile digest differs")
    try:
        value = json.loads(data)
    except (UnicodeError, ValueError):
        raise CodexSceneRejected("Codex scene profile JSON is malformed") from None
    return validate_scene_profile(value)


def _write_private(path: Path, data: bytes) -> None:
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC, 0o600)
    except FileExistsError:
        if _private_file(path) != data:
            raise CodexSceneRejected("Codex staged configuration changed on replay") from None
        return
    try:
        view = memoryview(data)
        while view:
            view = view[os.write(descriptor, view) :]
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def stage_codex_home(host_root: Path, profile: dict[str, Any]) -> dict[str, str]:
    """Write a one-turn private config with a key *path*, never key bytes."""
    validate_scene_profile(profile)
    if (
        os.name != "posix"
        or not re.fullmatch(r"p1-run-[a-f0-9]{32}", host_root.name)
        or host_root != Path(f"/run/user/{os.geteuid()}/acs-p1-codex") / host_root.name
    ):
        raise CodexSceneRejected("Codex host capacity path differs from the current run")
    _private_directory(host_root.parent)
    _private_directory(host_root)
    for name in ("bin", "codex-home", "cwd", "home", "tmp", "systemd-env"):
        _private_directory(host_root / name)
    executable = host_root / "bin" / "codex"
    info = executable.stat(follow_symlinks=False)
    if (
        executable.is_symlink()
        or not stat.S_ISREG(info.st_mode)
        or info.st_uid != os.geteuid()
        or info.st_nlink != 1
        or stat.S_IMODE(info.st_mode) != 0o500
        or info.st_size != profile["native_executable_size"]
        or _file_sha(executable) != profile["native_executable_sha256"]
    ):
        raise CodexSceneRejected("private native Codex executable differs")
    # The native app-server discovers its optional code-mode helper by name on
    # PATH during a turn, even when the packet exposes no tools.  Keep that
    # helper inside the same owner-private capacity when the reviewed install
    # provides it; never broaden PATH to the host installation.
    helper_source = Path(profile["native_executable_path"]).parent / "codex-code-mode-host"
    helper_target = host_root / "bin" / "codex-code-mode-host"
    if helper_source.exists():
        helper_info = helper_source.stat(follow_symlinks=False)
        if (
            helper_source.is_symlink()
            or not stat.S_ISREG(helper_info.st_mode)
            or helper_info.st_uid != os.geteuid()
            or helper_info.st_nlink != 1
        ):
            raise CodexSceneRejected("private code-mode host helper differs")
        _write_private(helper_target, helper_source.read_bytes())
        os.chmod(helper_target, 0o500)
    source_catalog = Path(profile["model_catalog_path"])
    catalog_bytes = _private_file(source_catalog)
    if (
        len(catalog_bytes) != profile["model_catalog_size"]
        or _sha(catalog_bytes) != profile["model_catalog_sha256"]
    ):
        raise CodexSceneRejected("reviewed native model catalog digest differs")
    try:
        catalog_value = json.loads(catalog_bytes)
    except (UnicodeError, ValueError) as error:
        raise CodexSceneRejected("reviewed native model catalog is malformed") from error
    models = catalog_value.get("models") if isinstance(catalog_value, dict) else None
    if not isinstance(models, list):
        raise CodexSceneRejected("reviewed native model catalog has no model list")
    matches = [
        item for item in models
        if isinstance(item, dict) and item.get("slug") == profile["model"]
    ]
    levels = matches[0].get("supported_reasoning_levels") if len(matches) == 1 else None
    if (
        len(matches) != 1
        or any(matches[0].get(name) != expected for name, expected in profile["model_catalog_entry"].items())
        or not isinstance(levels, list)
        or not any(
            isinstance(level, dict) and level.get("effort") == "low"
            for level in levels
        )
    ):
        raise CodexSceneRejected("reviewed catalog model or tool policy differs")
    catalog = host_root / "codex-home" / "models.json"
    _write_private(catalog, catalog_bytes)
    config = host_root / "codex-home" / "config.toml"
    quote = json.dumps
    contents = "\n".join(
        (
            f"model = {quote(profile['model'])}",
            f"model_reasoning_effort = {quote(profile['reasoning_effort'])}",
            f"model_provider = {quote(profile['provider_alias'])}",
            f"model_catalog_json = {quote(str(catalog))}",
            'approval_policy = "never"',
            'default_permissions = "achp-engineer"',
            "allow_login_shell = false",
            'web_search = "disabled"',
            "",
            "[features]",
            "multi_agent = false",
            "multi_agent_v2 = false",
            "shell_tool = false",
            "request_permissions_tool = false",
            "apps = false",
            "plugins = false",
            "recommended_plugins = false",
            "code_mode_host = true",
            "code_mode_only = false",
            "",
            "[shell_environment_policy]",
            'inherit = "none"',
            "experimental_use_profile = false",
            "",
            "[shell_environment_policy.set]",
            f'PATH = {quote(str(host_root / "bin") + ":/usr/bin:/bin")}',
            f"HOME = {quote(str(host_root / 'home'))}",
            f"TMPDIR = {quote(str(host_root / 'tmp'))}",
            "",
            "[permissions.achp-engineer.filesystem]",
            '":minimal" = "read"',
            f'{quote(str(host_root / "cwd"))} = "read"',
            "",
            f"[model_providers.{profile['provider_alias']}]",
            f"name = {quote('Reviewed P1 Codex provider')}",
            f"base_url = {quote(profile['provider_url'])}",
            f"wire_api = {quote(profile['wire_api'])}",
            "",
            f"[model_providers.{profile['provider_alias']}.auth]",
            f"command = {quote(profile['auth_command'])}",
            f"args = [{quote(profile['auth_key_ref_path'])}]",
            "timeout_ms = 5000",
            "refresh_interval_ms = 0",
            "",
        )
    )
    _write_private(config, contents.encode())
    return {
        "executable": str(executable),
        "config": str(config),
        "catalog": str(catalog),
        "cwd": str(host_root / "cwd"),
        "home": str(host_root / "home"),
        "tmp": str(host_root / "tmp"),
        "systemd_env": str(host_root / "systemd-env"),
    }


@dataclass(frozen=True, slots=True)
class TurnBudget:
    max_turn_starts: int = 1
    max_collect_reads: int = 6
    max_elapsed_seconds: int = 120

    def __post_init__(self) -> None:
        if (
            self.max_turn_starts != 1
            or not 1 <= self.max_collect_reads <= 6
            or not 1 <= self.max_elapsed_seconds <= 120
        ):
            raise CodexSceneRejected("Codex scene exceeds the reviewed request budget")


def collect_and_project_bounded(
    collector: Any,
    invocation: Any,
    *,
    budget: TurnBudget | None = None,
    pause: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> Any:
    """Poll only the original invocation; no retry can dispatch another turn."""
    if budget is None:
        budget = TurnBudget()
    started = clock()
    for index in range(budget.max_collect_reads):
        if clock() - started >= budget.max_elapsed_seconds:
            raise OutcomeUncertain("Codex terminal readback exceeded the scene deadline")
        try:
            disposition = collector.collect_and_project(invocation)
        except BoundaryRejected as error:
            if str(error) != "Driver has no exact terminal response":
                raise
        except OutcomeUncertain:
            pass
        else:
            if disposition.disposition != "applied":
                raise CodexSceneRejected("terminal response was not applied by Domain")
            return disposition
        if index + 1 < budget.max_collect_reads:
            remaining = budget.max_elapsed_seconds - (clock() - started)
            if remaining <= 0:
                raise OutcomeUncertain("Codex terminal readback exceeded the scene deadline")
            pause(min(2.0, remaining))
    raise OutcomeUncertain("original Codex turn has no bounded terminal readback")


def project_original_terminal(
    dispatch: dict[str, Any],
    node: NodeJournal,
    driver: CodexAppServerDriver,
    artifact_root: Path,
    *,
    budget: TurnBudget | None = None,
    pause: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    """Collect the existing turn into CAS/Node Outbox and actual PostgreSQL."""
    authority = dispatch["authority"]
    identity = dispatch["identity"]
    with authority._connect() as connection:
        row = connection.execute(
            "SELECT invocation_json FROM delivery_attempts "
            "WHERE message_id=%s AND attempt_id=%s AND dispatch_id=%s",
            (identity["message_id"], dispatch["attempt_id"], dispatch["dispatch_id"]),
        ).fetchone()
    if row is None or not isinstance(row[0], dict):
        raise CodexSceneRejected("PG immutable invocation is unavailable")
    invocation = InvocationRequest.model_validate_json(json.dumps(row[0]), strict=True)
    if invocation.invocation_id != dispatch["invocation_id"]:
        raise CodexSceneRejected("collector invocation differs from PG attempt")
    adapter = dispatch["adapter"]

    def snapshot(cursor: Any, observation: Any) -> AuthoritySnapshot:
        native = observation.identity
        message = cursor.execute(
            "SELECT packet_json,envelope_json,deadline,policy_hash,accepted_state_digest "
            "FROM delivery_messages WHERE tenant_id=%s AND message_id=%s FOR UPDATE",
            (native.tenant_id, native.message_id),
        ).fetchone()
        attempt = cursor.execute(
            "SELECT invocation_json,attempt_id,status FROM delivery_attempts "
            "WHERE tenant_id=%s AND message_id=%s ORDER BY ordinal DESC LIMIT 1 FOR UPDATE",
            (native.tenant_id, native.message_id),
        ).fetchone()
        if message is None or attempt is None or not isinstance(attempt[0], dict):
            raise CodexSceneRejected("current PG delivery identity is absent")
        recorded = InvocationRequest.model_validate_json(json.dumps(attempt[0]), strict=True)
        if NativeResponseCollector.dispatch_identity(recorded) != native:
            raise CodexSceneRejected("terminal response is not the current PG dispatch")
        envelope = message[1]
        grant = cursor.execute(
            "SELECT revoked_at,expires_at,principal_ref,authority_id,authority_incarnation "
            "FROM grants WHERE grant_ref=%s AND tenant_id=%s FOR UPDATE",
            (envelope["grant_ref"], native.tenant_id),
        ).fetchone()
        work = cursor.execute(
            "SELECT state,execution_status FROM work_items WHERE work_item_id=%s "
            "AND tenant_id=%s FOR UPDATE",
            (message[0]["work_item_id"], native.tenant_id),
        ).fetchone()
        authorized = bool(
            grant
            and grant[0] is None
            and grant[1] > datetime.now(UTC)
            and grant[2] == envelope["principal_ref"]
            and (grant[3], grant[4])
            == (
                authority.context.authority_id,
                authority.context.authority_incarnation,
            )
        )
        producer = False
        try:
            adapter._check_binding()
            producer = (
                node.node_id == native.node_id
                and node.boot_incarnation == native.boot_incarnation
                and any(
                    receipt.layer == "runtime_dispatched"
                    for receipt in node.receipts(native.operation_id)
                )
                and driver.journal.read(native.invocation_id)["state"] == "acknowledged"
            )
        except (RuntimeError, ValueError, TypeError, KeyError):
            producer = False
        return AuthoritySnapshot(
            committed_identity=NativeResponseCollector.dispatch_identity(recorded),
            producer_authenticated=producer,
            current_authority_valid=authorized,
            task_valid=bool(
                work
                and work[0] == "candidate"
                and work[1] not in {"blocked", "failed", "cancelled"}
            ),
            current_attempt_id=attempt[1],
            current_accepted_revision=message[0]["accepted_revision"],
            current_accepted_state_digest=message[4],
            deadline=message[2],
            principal_ref=envelope["principal_ref"],
            grant_ref=envelope["grant_ref"],
            policy_version="p1-codex:" + message[3],
        )

    outbox = node.response_outbox()
    projector = PostgresDelayedResponseAuthority(authority._dsn, snapshot)
    with LocalArtifactStore(artifact_root, scope_id="local-scope") as store:
        collector = NativeResponseCollector(
            adapter,
            outbox,
            artifact_response_store(store),
            projector.project,
        )
        disposition = collect_and_project_bounded(
            collector,
            invocation,
            budget=budget,
            pause=pause,
        )
        cached = outbox.by_invocation(NativeResponseCollector.dispatch_identity(invocation))
        if cached is None or cached.projection_id != disposition.projection_id:
            raise CodexSceneRejected("Node response Outbox differs from PG projection")
        artifact_sha = cached.response_artifact_ref.removeprefix("artifact:")
        artifact_path = artifact_root / artifact_sha[:2] / artifact_sha
        if _file_sha(artifact_path) != cached.response_digest:
            raise CodexSceneRejected("terminal response CAS readback differs")
        return {
            "projection_id": disposition.projection_id,
            "disposition": disposition.disposition,
            "response_artifact_ref": cached.response_artifact_ref,
            "response_digest": cached.response_digest,
            "native_response_ref": cached.native_response_ref,
        }


def read_codex_scene(
    dispatch: dict[str, Any],
    node: NodeJournal,
    driver: CodexAppServerDriver,
    projection: dict[str, Any],
    artifact_root: Path,
    *,
    source_commit: str,
    source_tree: str,
    run_id: str,
    temporal_endpoint: str,
    temporal_namespace: str,
    os_proof: dict[str, Any],
    budget: TurnBudget | None = None,
) -> dict[str, Any]:
    """Re-read all six authorities after native termination, then validate."""
    if budget is None:
        budget = TurnBudget()
    authority = dispatch["authority"]
    identity = dispatch["identity"]
    message_id, operation_id = identity["message_id"], identity["operation_id"]
    attempt_id = dispatch["attempt_id"]
    invocation_id = dispatch["invocation_id"]
    dispatch_id = dispatch["dispatch_id"]
    with authority._connect() as connection:
        row = connection.execute(
            "SELECT command_id FROM delivery_messages WHERE message_id=%s AND operation_id=%s",
            (message_id, operation_id),
        ).fetchone()
        if row is None:
            raise CodexSceneRejected("Domain message disappeared before readback")
        command_id = row[0]
        statements = (
            ("SELECT count(*) FROM delivery_attempts WHERE message_id=%s", (message_id,)),
            (
                (
                    "SELECT count(*) FROM delivery_receipts WHERE message_id=%s "
                    "AND layer='runtime_dispatched'"
                ),
                (message_id,),
            ),
            ("SELECT count(*) FROM domain_events WHERE command_id=%s", (command_id,)),
            ("SELECT count(*) FROM outbox WHERE operation_id=%s", (operation_id,)),
            (
                (
                    "SELECT count(*) FROM native_response_observations WHERE invocation_id=%s "
                    "AND disposition='applied'"
                ),
                (invocation_id,),
            ),
            (
                (
                    "SELECT count(*) FROM delivery_receipts WHERE message_id=%s "
                    "AND layer='response_received'"
                ),
                (message_id,),
            ),
        )
        pg_counts = [
            connection.execute(statement, params).fetchone()[0] for statement, params in statements
        ]
        selection = connection.execute(
            "SELECT selection_json->>'machine_id',selection_json->>'node_id' "
            "FROM delivery_attempts WHERE message_id=%s AND attempt_id=%s",
            (message_id, attempt_id),
        ).fetchone()
    with node._connect() as connection:
        node_counts = [
            connection.execute(statement, params).fetchone()[0]
            for statement, params in (
                ("SELECT count(*) FROM mailbox WHERE message_id=?", (message_id,)),
                (
                    "SELECT count(*) FROM delivery_invocations WHERE invocation_id=?",
                    (invocation_id,),
                ),
                (
                    (
                        "SELECT count(*) FROM native_response_observations WHERE invocation_id=? "
                        "AND state='applied'"
                    ),
                    (invocation_id,),
                ),
            )
        ]
    with driver.journal._connect() as connection:
        rows = connection.execute(
            "SELECT kind,body FROM driver_events WHERE operation_id=? ORDER BY sequence",
            (invocation_id,),
        ).fetchall()
    decoded = [(kind, json.loads(body)) for kind, body in rows]
    starts = [
        body
        for kind, body in decoded
        if kind == "rpc_dispatch" and body.get("method") == "turn/start"
    ]
    attempts = [
        body
        for kind, body in decoded
        if kind == "rpc_intent" and body.get("method") == "turn/start"
    ]
    terminal = [body for kind, body in decoded if kind == "terminal_observation"]
    turn_dispatch_position = next(
        (
            index
            for index, (kind, body) in enumerate(decoded)
            if kind == "rpc_dispatch" and body.get("method") == "turn/start"
        ),
        len(decoded),
    )
    acknowledged = driver.journal.read(invocation_id)
    if not acknowledged or not isinstance(acknowledged.get("result"), dict):
        raise CodexSceneRejected("Driver original ACK disappeared")
    first = acknowledged["result"]
    if not terminal:
        raise CodexSceneRejected("Driver terminal observation is missing")
    latest = terminal[-1]
    assistant = latest.get("assistant_messages")
    answer = "\n".join(item.get("text", "") for item in assistant or [] if isinstance(item, dict))

    async def temporal_readback() -> str:
        client = await Client.connect(temporal_endpoint, namespace=temporal_namespace)
        handle = client.get_workflow_handle(
            dispatch["workflow_id"],
            run_id=dispatch["provider_run_id"],
        )
        result = await handle.result()
        return result.get("status", "unknown") if isinstance(result, dict) else "unknown"

    provider_status = asyncio.run(temporal_readback())
    artifact_sha = projection["response_artifact_ref"].removeprefix("artifact:")
    artifact_readback = (
        projection["response_artifact_ref"].startswith("artifact:")
        and _file_sha(artifact_root / artifact_sha[:2] / artifact_sha) == artifact_sha
    )
    value = {
        "run_id": run_id,
        "source_commit": source_commit,
        "source_tree": source_tree,
        "machine_id": node.machine_id,
        "node_id": node.node_id,
        "message_id": message_id,
        "command_id": command_id,
        "operation_id": operation_id,
        "attempt_id": attempt_id,
        "invocation_id": invocation_id,
        "dispatch_id": dispatch_id,
        "thread_id": first.get("thread_id"),
        "session_id": first.get("session_id"),
        "turn_id": first.get("turn_id"),
        "pg": {
            "identity": [message_id, operation_id, attempt_id, invocation_id, dispatch_id],
            "selection_machine_id": selection[0] if selection else None,
            "selection_node_id": selection[1] if selection else None,
            "attempt_count": pg_counts[0],
            "dispatch_marker_count": pg_counts[1],
            "event_count": pg_counts[2],
            "outbox_count": pg_counts[3],
            "response_projection_count": pg_counts[4],
            "response_receipt_count": pg_counts[5],
        },
        "node": {
            "identity": [message_id, operation_id, attempt_id, invocation_id, dispatch_id],
            "machine_id": node.machine_id,
            "node_id": node.node_id,
            "journal_name": Path(node._path).name,
            "mailbox_count": node_counts[0],
            "invocation_count": node_counts[1],
            "response_outbox_count": node_counts[2],
            "boot_current": node.boot_incarnation == driver.identity.node_boot_id,
        },
        "temporal": {
            "operation_id": operation_id,
            "workflow_id": dispatch["workflow_id"],
            "run_id": dispatch["provider_run_id"],
            "readback_status": ("completed" if provider_status == "delivered" else provider_status),
        },
        "driver": {
            "invocation_id": invocation_id,
            "journal_name": Path(driver.journal.path).name,
            "native_identity": [
                first.get("thread_id"),
                first.get("session_id"),
                first.get("turn_id"),
            ],
            "turn_start_dispatch_count": len(starts),
            "turn_start_attempt_count": len(attempts),
            "server_request_count": sum(
                kind == "native_event" and body.get("kind") == "server_request"
                for kind, body in decoded
            ),
            "collect_read_count": sum(
                kind == "rpc_intent" and body.get("method") == "thread/read"
                for kind, body in decoded[turn_dispatch_position + 1 :]
            ),
            "terminal_status": latest.get("native_status"),
            "user_client_id": attempts[0].get("params", {}).get("clientUserMessageId")
            if attempts
            else None,
            "unique_user_message": len(attempts) == 1,
            "assistant_text_exact": answer.strip() == "ACS_P1_CODEX_API_OK",
            "terminal_event_sha256": _sha(_canonical(latest)),
            "token_usage": native_usage_observation(
                decoded, first.get("thread_id"), first.get("turn_id")
            ),
        },
        "response": {
            "invocation_id": invocation_id,
            "native_identity": [
                latest.get("thread_id"),
                latest.get("session_id"),
                latest.get("turn_id"),
            ],
            "projection_id": projection["projection_id"],
            "response_artifact_ref": projection["response_artifact_ref"],
            "response_digest": projection["response_digest"],
            "disposition": projection["disposition"],
            "artifact_readback": artifact_readback,
            "digest_match": projection["response_digest"] == artifact_sha,
        },
        "os": os_proof,
    }
    validate_lineage(value, budget=budget)
    return value


def read_codex_layer(
    loopback: dict[str, Any],
    ledger_root: Path,
    row: dict[str, Any],
    kind: str,
) -> dict[str, Any]:
    """Re-read one persisted authority after the model process has stopped."""
    if kind not in {"command_output", "postgresql", "sqlite", "temporal", "driver", "os"}:
        raise CodexSceneRejected("unknown Codex readback layer")
    lineage = json.loads(row["lineage_json"])
    validate_lineage(lineage)
    message_id = lineage["message_id"]
    operation_id = lineage["operation_id"]
    invocation_id = lineage["invocation_id"]
    if kind == "command_output":
        raw = ledger_root / row["raw_path"]
        if _file_sha(raw) != row["test_digest"] or json.loads(raw.read_text()) != lineage:
            raise CodexSceneRejected("Codex command evidence changed")
        return {"command_output": True, "lineage_sha256": _sha(_canonical(lineage))}
    if kind == "postgresql":
        scoped = make_conninfo(
            loopback["postgres_dsn"],
            options=f"-c search_path={row['pg_schema']}",
        )
        with psycopg.connect(scoped) as connection:
            message = connection.execute(
                "SELECT command_id,operation_id,state,receipt_high_water "
                "FROM delivery_messages WHERE message_id=%s",
                (message_id,),
            ).fetchone()
            attempts = connection.execute(
                "SELECT attempt_id,dispatch_id,status,selection_json->>'machine_id',"
                "selection_json->>'node_id' FROM delivery_attempts "
                "WHERE message_id=%s ORDER BY ordinal",
                (message_id,),
            ).fetchall()
            markers = connection.execute(
                "SELECT receipt_id,attempt_id,dispatch_id FROM delivery_receipts "
                "WHERE message_id=%s AND layer='runtime_dispatched'",
                (message_id,),
            ).fetchall()
            responses = connection.execute(
                "SELECT receipt_id,attempt_id,dispatch_id FROM delivery_receipts "
                "WHERE message_id=%s AND layer='response_received'",
                (message_id,),
            ).fetchall()
            projections = connection.execute(
                "SELECT projection_id,invocation_id,attempt_id,dispatch_id,response_digest,"
                "disposition FROM native_response_observations WHERE message_id=%s",
                (message_id,),
            ).fetchall()
            provider = connection.execute(
                "SELECT provider_workflow_id,provider_run_id FROM operations WHERE operation_id=%s",
                (operation_id,),
            ).fetchone()
        if (
            message != (lineage["command_id"], operation_id, "delivered", "response_received")
            or attempts != [
                (
                    lineage["attempt_id"], lineage["dispatch_id"], "delivered",
                    lineage["machine_id"], lineage["node_id"],
                )
            ]
            or len(markers) != 1
            or markers[0][1:]
            != (
                lineage["attempt_id"],
                lineage["dispatch_id"],
            )
            or len(responses) != 1
            or responses[0][1:]
            != (
                lineage["attempt_id"],
                lineage["dispatch_id"],
            )
            or projections
            != [
                (
                    lineage["response"]["projection_id"],
                    invocation_id,
                    lineage["attempt_id"],
                    lineage["dispatch_id"],
                    lineage["response"]["response_digest"],
                    "applied",
                )
            ]
            or provider
            != (
                lineage["temporal"]["workflow_id"],
                lineage["temporal"]["run_id"],
            )
        ):
            raise CodexSceneRejected("Codex PostgreSQL authoritative lineage changed")
        return {"postgresql_readback": True, "receipt_ids": [markers[0][0], responses[0][0]]}
    if kind in {"sqlite", "driver"} and isinstance(row.get("host_request_json"), str):
        try:
            request = CodexHostRequest.model_validate_json(
                row["host_request_json"],
                strict=True,
            )
        except ValueError as error:
            raise CodexSceneRejected("restricted host readback request differs") from error
        if (
            request.action != "readback"
            or request.run_id != lineage["run_id"]
            or request.message_id != message_id
            or request.command_id != lineage["command_id"]
            or request.operation_id != operation_id
        ):
            raise CodexSceneRejected("restricted host readback left original attempt")
        result = _host_result_from_socket(request, lineage)
        if result.scene_readback != lineage or result.scene_readback_sha256 != _sha(
            _canonical(lineage)
        ):
            raise CodexSceneRejected("restricted host Node/Driver readback changed")
        if kind == "sqlite":
            return {"sqlite_readback": True, "node_state_sha256": _sha(_canonical(lineage["node"]))}
        return {"driver_readback": True, "artifact_sha256": lineage["response"]["response_digest"]}
    node_name = lineage["node"].get("journal_name")
    if not isinstance(node_name, str) or not re.fullmatch(r"[A-Za-z0-9._-]{1,128}", node_name):
        raise CodexSceneRejected("Node journal name is not bounded")
    node_path = ledger_root / node_name
    if kind == "sqlite":
        with sqlite3.connect(node_path) as connection:
            mailbox = connection.execute(
                "SELECT command_id,operation_id FROM mailbox WHERE message_id=?",
                (message_id,),
            ).fetchall()
            invocation = connection.execute(
                "SELECT dispatch_id,state FROM delivery_invocations WHERE invocation_id=?",
                (invocation_id,),
            ).fetchall()
            outbox = connection.execute(
                "SELECT projection_id,state FROM native_response_observations "
                "WHERE invocation_id=?",
                (invocation_id,),
            ).fetchall()
        if (
            mailbox != [(lineage["command_id"], operation_id)]
            or invocation != [(lineage["dispatch_id"], "acknowledged")]
            or outbox != [(lineage["response"]["projection_id"], "applied")]
        ):
            raise CodexSceneRejected("Codex SQLite Node lineage changed")
        return {"sqlite_readback": True, "node_journal_sha256": _file_sha(node_path)}
    if kind == "temporal":

        async def read():
            client = await Client.connect(
                loopback["temporal_endpoint"],
                namespace=loopback["temporal_namespace"],
            )
            handle = client.get_workflow_handle(
                lineage["temporal"]["workflow_id"],
                run_id=lineage["temporal"]["run_id"],
            )
            return await handle.result()

        result = asyncio.run(read())
        if not isinstance(result, dict) or result.get("status") != "delivered":
            raise CodexSceneRejected("Codex Temporal Workflow readback changed")
        return {"temporal_readback": True, "run_id": lineage["temporal"]["run_id"]}
    if kind == "driver":
        driver_name = lineage["driver"].get("journal_name")
        if not isinstance(driver_name, str) or not re.fullmatch(
            r"[A-Za-z0-9._-]{1,128}", driver_name
        ):
            raise CodexSceneRejected("Driver journal name is not bounded")
        path = ledger_root / driver_name
        with sqlite3.connect(path) as connection:
            events = connection.execute(
                "SELECT kind,body FROM driver_events WHERE operation_id=? ORDER BY sequence",
                (invocation_id,),
            ).fetchall()
        decoded = [(kind, json.loads(body)) for kind, body in events]
        starts = [
            body
            for event, body in decoded
            if event == "rpc_dispatch" and body.get("method") == "turn/start"
        ]
        terminal = [body for event, body in decoded if event == "terminal_observation"]
        artifact_sha = lineage["response"]["response_digest"]
        artifact = ledger_root / "artifacts" / artifact_sha[:2] / artifact_sha
        if (
            len(starts) != 1
            or not terminal
            or terminal[-1].get("turn_id") != lineage["turn_id"]
            or _file_sha(artifact) != artifact_sha
        ):
            raise CodexSceneRejected("Codex Driver or CAS readback changed")
        return {"driver_readback": True, "artifact_sha256": artifact_sha}
    request_value = row.get("host_request_json")
    if not isinstance(request_value, str):
        raise CodexSceneRejected("restricted host OS request identity is unavailable")
    try:
        request = CodexHostRequest.model_validate_json(request_value, strict=True)
    except ValueError as error:
        raise CodexSceneRejected("restricted host OS request is malformed") from error
    if (
        request.run_id != lineage["run_id"]
        or request.message_id != lineage["message_id"]
        or request.command_id != lineage["command_id"]
        or request.operation_id != lineage["operation_id"]
        or request.source_commit != lineage["source_commit"]
    ):
        raise CodexSceneRejected("restricted host OS request left original lineage")
    observed = read_host_os_from_socket(request, lineage)
    return {
        "os_readback": True,
        "unit_inactive": True,
        "containment_id": observed["containment_id"],
    }


def dispatch_host_without_ack(
    request: CodexHostRequest,
    *,
    socket_path: Path = Path("/run/acs-p1/codex-host.sock"),
) -> None:
    """Inject one response ACK loss after sending the original request bytes."""
    if (
        os.name != "posix"
        or request.action != "dispatch"
        or socket_path != Path("/run/acs-p1/codex-host.sock")
    ):
        raise CodexSceneRejected("Codex ACK-loss injection left the fixed host socket")
    parent = None
    try:
        parent, _ = private_parent(socket_path.parent)
        info = os.stat(socket_path.name, dir_fd=parent, follow_symlinks=False)
    except (OSError, PathSecurityRejected) as error:
        raise CodexSceneRejected("Codex ACK-loss socket path is unsafe") from error
    finally:
        if parent is not None:
            os.close(parent)
    if not stat.S_ISSOCK(info.st_mode) or info.st_uid != os.geteuid():
        raise CodexSceneRejected("Codex ACK-loss socket identity is unsafe")
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
            connection.settimeout(5)
            connection.connect(str(socket_path))
            _pid, uid, _gid = struct.unpack(
                "3i",
                connection.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12),
            )
            if uid != os.geteuid():
                raise CodexSceneRejected("Codex ACK-loss host peer differs")
            connection.sendall(request.model_dump_json().encode() + b"\n")
            connection.shutdown(socket.SHUT_RDWR)
    except OSError as error:
        raise CodexSceneRejected("Codex ACK-loss request send is unverified") from error


def _host_result_from_socket(
    request: CodexHostRequest,
    lineage: dict[str, Any],
    *,
    socket_path: Path = Path("/run/acs-p1/codex-host.sock"),
    timeout_seconds: float = 5,
) -> CodexHostResult:
    """Send only the fixed HostNode request across an owner-pinned Unix socket."""
    if (
        os.name != "posix"
        or not socket_path.is_absolute()
        or socket_path != Path("/run/acs-p1/codex-host.sock")
    ):
        raise CodexSceneRejected("restricted host OS socket is unavailable")
    parent = None
    try:
        parent, _ = private_parent(socket_path.parent)
        info = os.stat(socket_path.name, dir_fd=parent, follow_symlinks=False)
    except (OSError, PathSecurityRejected) as error:
        raise CodexSceneRejected("restricted host OS socket path is unsafe") from error
    finally:
        if parent is not None:
            os.close(parent)
    if not stat.S_ISSOCK(info.st_mode) or info.st_uid != os.geteuid():
        raise CodexSceneRejected("restricted host OS socket identity is unsafe")
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
            connection.settimeout(timeout_seconds)
            connection.connect(str(socket_path))
            _pid, uid, _gid = struct.unpack(
                "3i",
                connection.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12),
            )
            if uid != os.geteuid():
                raise CodexSceneRejected("restricted host OS peer differs")
            connection.sendall(request.model_dump_json().encode() + b"\n")
            received = bytearray()
            while len(received) <= 262144 and not received.endswith(b"\n"):
                chunk = connection.recv(min(8192, 262145 - len(received)))
                if not chunk:
                    break
                received.extend(chunk)
    except OSError as error:
        raise CodexSceneRejected("restricted host OS readback failed") from error
    if len(received) > 262144 or not received.endswith(b"\n"):
        raise CodexSceneRejected("restricted host OS response frame differs")
    try:
        result = CodexHostResult.model_validate_json(received[:-1], strict=True)
    except ValueError as error:
        raise CodexSceneRejected("restricted host OS response schema differs") from error
    if (
        result.run_id != lineage["run_id"]
        or result.message_id != lineage["message_id"]
        or result.command_id != lineage["command_id"]
        or result.operation_id != lineage["operation_id"]
        or result.status != "delivered"
    ):
        raise CodexSceneRejected("restricted host OS readback left original delivery")
    return result


def read_host_os_from_socket(
    request: CodexHostRequest,
    lineage: dict[str, Any],
    *,
    socket_path: Path = Path("/run/acs-p1/codex-host.sock"),
) -> dict[str, Any]:
    """Read a fixed stopped-unit proof from the host Node, without guest bus access."""
    if request.action != "readback":
        raise CodexSceneRejected("restricted host OS requires readback action")
    result = _host_result_from_socket(request, lineage, socket_path=socket_path)
    if not isinstance(result.os_observation, dict):
        raise CodexSceneRejected("restricted host OS termination proof is missing")
    proof = result.os_observation
    expected = lineage["os"]
    for field in ("unit", "containment_id", "birth_ref", "invocation_id"):
        if not expected.get(field) or proof.get(field) != expected[field]:
            raise CodexSceneRejected("restricted host OS process identity changed")
    if (
        proof.get("verified") is not True
        or proof.get("remaining_pids") != []
        or proof.get("root_exited") is not True
        or proof.get("wrapper_exited") is not True
        or proof.get("active_state") not in {"inactive", "failed"}
    ):
        raise CodexSceneRejected("restricted host OS termination proof is incomplete")
    return proof


def validate_lineage(
    value: dict[str, Any],
    *,
    budget: TurnBudget | None = None,
) -> dict[str, Any]:
    """Bind real readbacks to one PG attempt and one acknowledged Codex turn."""
    if budget is None:
        budget = TurnBudget()
    if not isinstance(value, dict) or set(value) != {
        "run_id",
        "source_commit",
        "source_tree",
        "machine_id",
        "node_id",
        "message_id",
        "command_id",
        "operation_id",
        "attempt_id",
        "invocation_id",
        "dispatch_id",
        "thread_id",
        "session_id",
        "turn_id",
        "pg",
        "node",
        "temporal",
        "driver",
        "os",
        "response",
    }:
        raise CodexSceneRejected("Codex scene readback shape differs")
    for name in (
        "run_id",
        "message_id",
        "command_id",
        "operation_id",
        "attempt_id",
        "invocation_id",
        "dispatch_id",
        "thread_id",
        "session_id",
        "turn_id",
        "machine_id",
        "node_id",
    ):
        _text(value[name], name)
    for name in ("source_commit", "source_tree"):
        digest = value[name]
        if (
            not isinstance(digest, str)
            or len(digest) != 40
            or any(c not in "0123456789abcdef" for c in digest)
        ):
            raise CodexSceneRejected(f"{name} is not an exact Git object ID")
    expected_invocation = f"delivery-invocation:{value['attempt_id']}"
    expected_dispatch = f"delivery-dispatch:{value['attempt_id']}"
    if value["invocation_id"] != expected_invocation or value["dispatch_id"] != expected_dispatch:
        raise CodexSceneRejected("native invocation differs from the PG attempt")
    pg, node, temporal = value["pg"], value["node"], value["temporal"]
    driver, system, response = value["driver"], value["os"], value["response"]
    if any(not isinstance(layer, dict) for layer in (pg, node, temporal, driver, system, response)):
        raise CodexSceneRejected("a required authority layer is absent")
    identity = [
        value["message_id"],
        value["operation_id"],
        value["attempt_id"],
        value["invocation_id"],
        value["dispatch_id"],
    ]
    if (
        pg.get("selection_machine_id") != value["machine_id"]
        or pg.get("selection_node_id") != value["node_id"]
    ):
        raise CodexSceneRejected("PostgreSQL attempt machine identity differs")
    if pg.get("identity") != identity or not all(
        _count(pg.get(name), 1)
        for name in (
            "attempt_count",
            "dispatch_marker_count",
            "event_count",
            "outbox_count",
            "response_projection_count",
            "response_receipt_count",
        )
    ):
        raise CodexSceneRejected("PostgreSQL did not bind one dispatch and response projection")
    if (
        node.get("identity") != identity
        or node.get("machine_id") != value["machine_id"]
        or node.get("node_id") != value["node_id"]
        or not all(
            _count(node.get(name), 1)
            for name in (
                "mailbox_count",
                "invocation_count",
                "response_outbox_count",
            )
        )
        or node.get("boot_current") is not True
    ):
        raise CodexSceneRejected("SQLite Node did not bind the same invocation")
    if (
        temporal.get("operation_id") != value["operation_id"]
        or temporal.get("workflow_id") != "acs-delivery/" + value["operation_id"]
        or not _text(temporal.get("run_id"), "Temporal run_id")
        or temporal.get("readback_status") != "completed"
    ):
        raise CodexSceneRejected("Temporal did not own the same durable operation")
    native_identity = [value["thread_id"], value["session_id"], value["turn_id"]]
    collect_reads = driver.get("collect_read_count")
    elapsed = system.get("elapsed_seconds")
    if (
        driver.get("invocation_id") != value["invocation_id"]
        or driver.get("native_identity") != native_identity
        or not _count(driver.get("turn_start_dispatch_count"), budget.max_turn_starts)
        or not _count(driver.get("turn_start_attempt_count"), budget.max_turn_starts)
        or type(collect_reads) is not int
        or not 1 <= collect_reads <= budget.max_collect_reads
        or driver.get("terminal_status") != "completed"
        or driver.get("user_client_id") != value["message_id"]
        or driver.get("unique_user_message") is not True
        or driver.get("assistant_text_exact") is not True
        or not _count(driver.get("server_request_count"), 0)
    ):
        raise CodexSceneRejected("Driver did not prove one original completed turn")
    usage = driver.get("token_usage")
    if (
        not isinstance(usage, dict)
        or usage.get("status") not in {"observed", "not_observed"}
        or type(usage.get("notification_count")) is not int
        or usage["notification_count"] < 0
        or not isinstance(driver.get("terminal_event_sha256"), str)
        or not re.fullmatch(r"[a-f0-9]{64}", driver["terminal_event_sha256"])
        or usage["status"] == "not_observed" and usage["notification_count"] != 0
        or usage["status"] == "observed" and (
            usage["notification_count"] < 1
            or not re.fullmatch(r"[a-f0-9]{64}", usage.get("native_notification_sha256", ""))
            or not _valid_token_counts(usage.get("last"))
            or not _valid_token_counts(usage.get("total"))
        )
    ):
        raise CodexSceneRejected("Driver token/terminal observation is incomplete")
    if (
        response.get("invocation_id") != value["invocation_id"]
        or response.get("native_identity") != native_identity
        or response.get("disposition") != "applied"
        or response.get("artifact_readback") is not True
        or response.get("digest_match") is not True
    ):
        raise CodexSceneRejected("terminal response artifact or projection differs")
    if (
        system.get("termination_verified") is not True
        or system.get("remaining_pids") != []
        or system.get("wrapper_exited") is not True
        or not _count(system.get("environment_files_remaining"), 0)
        or not _count(system.get("model_prompt_count"), 1)
        or type(elapsed) not in (int, float)
        or not 0 < elapsed <= budget.max_elapsed_seconds
    ):
        raise CodexSceneRejected("systemd ownership or request budget is incomplete")
    observed = system.get("observed_at")
    try:
        timestamp = datetime.fromisoformat(observed)
    except (TypeError, ValueError):
        raise CodexSceneRejected("OS observation time is malformed") from None
    if timestamp.tzinfo is None or timestamp.astimezone(UTC) > datetime.now(UTC):
        raise CodexSceneRejected("OS observation is naive or future dated")
    return {"lineage_sha256": _sha(_canonical(value)), "model_calls": 1}
