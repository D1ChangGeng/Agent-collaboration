"""Identity-preserving classification of historical command journal entries."""
from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal

FOUNDATION_HASH_VERSION = "e55-v0"
HARDENED_HASH_VERSION = "912-v1"
LEGACY_HASH_VERSION = "legacy-unclassified"
CURRENT_HASH_VERSION = "v2"
MigrationAction = Literal["verify", "replay", "conflict", "quarantine"]


@dataclass(frozen=True, slots=True)
class LegacyCommandRecord:
    tenant_id: str
    idempotency_key: str | None
    command_id: str | None
    payload_hash: str | None
    result_json: Mapping[str, Any] | str | None
    hash_version: str | None = None
    # Obtained from a trusted historical event, never from the retry request.
    principal_ref: str | None = None


@dataclass(frozen=True, slots=True)
class MigrationDecision:
    action: MigrationAction
    command_id: str | None
    hash_version: str | None
    reason: str


def _valid_identity(value: object) -> bool:
    return (
        isinstance(value, str)
        and 0 < len(value) <= 256
        and bool(value.strip())
        and not any(ord(char) < 32 or 127 <= ord(char) <= 159 for char in value)
    )


def _result_mapping(value: Mapping[str, Any] | str | None) -> Mapping[str, Any] | None:
    if value is None:
        return None
    if isinstance(value, Mapping):
        return value
    if not isinstance(value, str):
        return None
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError):
        return None
    return parsed if isinstance(parsed, Mapping) else None


def recover_original_command_id(record: LegacyCommandRecord) -> str | None:
    result = _result_mapping(record.result_json)
    if result is None:
        return None
    column = record.command_id
    if column is not None and not _valid_identity(column):
        return None
    present = "command_id" in result
    result_id = result.get("command_id")
    if present and not _valid_identity(result_id):
        return None
    if column is not None and present and column != result_id:
        return None
    identity = column if column is not None else result_id
    if not _valid_identity(identity):
        return None
    if identity == record.idempotency_key and not present:
        return None
    # Preserve original bytes, including any significant surrounding spaces.
    return identity


def _version(value: str | None) -> str | None:
    if value in (None, "1", "v1", LEGACY_HASH_VERSION):
        return LEGACY_HASH_VERSION
    if value in (FOUNDATION_HASH_VERSION, HARDENED_HASH_VERSION, CURRENT_HASH_VERSION):
        return value
    return None


def migrate_legacy_record(record: LegacyCommandRecord) -> MigrationDecision:
    identity = recover_original_command_id(record)
    version = _version(record.hash_version)
    if identity is None:
        return MigrationDecision("quarantine", None, version, "missing_or_conflicting_original_command_id")
    if version is None:
        return MigrationDecision("quarantine", identity, record.hash_version, "unknown_hash_version")
    if version == CURRENT_HASH_VERSION:
        return MigrationDecision("conflict", identity, version, "current_hash_requires_current_dedup")
    if not isinstance(record.payload_hash, str) or not re.fullmatch(r"[a-f0-9]{64}", record.payload_hash):
        return MigrationDecision("quarantine", identity, version, "missing_or_malformed_legacy_hash")
    return MigrationDecision("verify", identity, version, "legacy_identity_requires_hash_verification")


def legacy_command_hash(
    command: Any,
    extra: Mapping[str, Any] | None = None,
    *,
    hash_version: str = HARDENED_HASH_VERSION,
) -> str:
    """Reproduce a pinned historical algorithm without using the new model dump."""
    if hash_version == FOUNDATION_HASH_VERSION:
        value = {
            "command_type": command.command_type,
            "target_kind": command.target_kind,
            "target_id": command.target_id,
            "expected_revision": command.expected_revision,
            "payload": command.payload,
            "extra": dict(extra or {}),
        }
    elif hash_version == HARDENED_HASH_VERSION:
        value = {
            "command_id": command.command_id,
            "command_type": command.command_type,
            "idempotency_key": command.idempotency_key,
            "correlation_id": command.correlation_id,
            "tenant_id": command.tenant_id,
            "authority_id": command.authority_id,
            "authority_incarnation": command.authority_incarnation,
            "principal_ref": command.principal_ref,
            "grant_ref": command.grant_ref,
            "target_kind": command.target_kind,
            "target_id": command.target_id,
            "expected_revision": command.expected_revision,
            "issued_at": command.issued_at.isoformat(),
            "deadline": command.deadline.isoformat(),
            "payload": command.payload,
            "extra": dict(extra or {}),
        }
    else:
        raise ValueError("a pinned historical hash algorithm is required")
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def classify_replay(
    record: LegacyCommandRecord,
    command: Any,
    *,
    extra: Mapping[str, Any] | None = None,
) -> MigrationDecision:
    decision = migrate_legacy_record(record)
    if decision.action != "verify":
        return decision

    def quarantine(reason: str) -> MigrationDecision:
        return MigrationDecision("quarantine", decision.command_id, decision.hash_version, reason)

    if (
        command.command_id != decision.command_id
        or command.tenant_id != record.tenant_id
        or command.idempotency_key != record.idempotency_key
    ):
        return quarantine("command_identity_mismatch")
    if getattr(command, "causation_id", None) is not None:
        return quarantine("unverifiable_legacy_causation")
    if record.principal_ref is not None and command.principal_ref != record.principal_ref:
        return quarantine("legacy_principal_mismatch")
    versions = (
        (FOUNDATION_HASH_VERSION, HARDENED_HASH_VERSION)
        if decision.hash_version == LEGACY_HASH_VERSION
        else (decision.hash_version,)
    )
    try:
        matches = [
            version for version in versions
            if legacy_command_hash(command, extra, hash_version=version) == record.payload_hash
        ]
    except (AttributeError, TypeError, ValueError, OverflowError):
        return quarantine("invalid_legacy_command_input")
    if len(matches) != 1:
        return quarantine("legacy_hash_mismatch_or_ambiguity")
    actual_version = matches[0]
    if actual_version == FOUNDATION_HASH_VERSION and not _valid_identity(record.principal_ref):
        return quarantine("missing_legacy_principal_provenance")
    return MigrationDecision("replay", decision.command_id, actual_version, "historical_hash_and_identity_verified")
