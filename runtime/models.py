from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, ValidationInfo, field_validator

from runtime.json_payload import bounded_payload


class WorkItemState(StrEnum):
    CANDIDATE = "candidate"
    ACCEPTANCE_READY = "acceptance_ready"
    ACCEPTED = "accepted"


class ExecutionStatus(StrEnum):
    READY = "ready"
    RUNNING = "running"
    BLOCKED = "blocked"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass(frozen=True, slots=True)
class AuthenticatedContext:
    tenant_id: str
    authority_id: str
    authority_incarnation: str
    principal_ref: str
    grant_ref: str
    credential_hash: str = ""


type PayloadValue = JsonValue


class CommandEnvelope(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["1.0"] = "1.0"
    # v2 seals complete command input, including causation. v1 remains
    # readable by migration/replay code for pre-hardening rows.
    hash_version: Literal["v1", "v2"] = "v2"
    command_id: str = Field(min_length=1, max_length=256)
    command_type: str = Field(min_length=1, max_length=128)
    idempotency_key: str = Field(min_length=1, max_length=256)
    correlation_id: str = Field(min_length=1, max_length=256)
    causation_id: str | None = Field(default=None, max_length=256)
    tenant_id: str = Field(min_length=1, max_length=256)
    authority_id: str = Field(min_length=1, max_length=256)
    authority_incarnation: str = Field(min_length=1, max_length=256)
    principal_ref: str = Field(min_length=1, max_length=256)
    grant_ref: str = Field(min_length=1, max_length=256)
    target_kind: Literal[
        "work_item", "message", "lease", "effect", "node", "runtime", "attempt",
        "authority_transport_key", "connection", "endpoint", "recovery", "projection",
    ]
    target_id: str = Field(min_length=1, max_length=256)
    expected_revision: int = Field(ge=0)
    issued_at: datetime
    deadline: datetime
    payload: dict[str, PayloadValue] = Field(default_factory=dict)

    @field_validator("payload", mode="before")
    @classmethod
    def bounded_json_payload(cls, value):
        return bounded_payload(value)

    @field_validator("deadline")
    @classmethod
    def deadline_after_issue(cls, value: datetime, info: ValidationInfo) -> datetime:
        issued_at = info.data.get("issued_at")
        if isinstance(issued_at, datetime) and value < issued_at:
            raise ValueError("deadline must not precede issued_at")
        return value

    def canonical_input(self, extra: Mapping[str, Any] | None = None) -> dict[str, Any]:
        value = self.model_dump(mode="json")
        if extra:
            value["extra"] = dict(extra)
        return value

    def canonical_hash(self, extra: Mapping[str, Any] | None = None) -> str:
        payload = json.dumps(self.canonical_input(extra), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def legacy_hash(self, extra: Mapping[str, Any] | None = None) -> str:
        """Hash the pre-v2 domain._hash input exactly."""
        value = {
            "command_id": self.command_id,
            "command_type": self.command_type,
            "idempotency_key": self.idempotency_key,
            "correlation_id": self.correlation_id,
            "tenant_id": self.tenant_id,
            "authority_id": self.authority_id,
            "authority_incarnation": self.authority_incarnation,
            "principal_ref": self.principal_ref,
            "grant_ref": self.grant_ref,
            "target_kind": self.target_kind,
            "target_id": self.target_id,
            "expected_revision": self.expected_revision,
            "issued_at": self.issued_at.isoformat(),
            "deadline": self.deadline.isoformat(),
            "payload": self.payload,
            "extra": dict(extra or {}),
        }
        payload = json.dumps(value, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class CommandResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    command_id: str
    operation_id: str
    target_id: str
    revision: int
    state: str
    receipt_layer: str = "accepted_by_authority"
    duplicate: bool = False


class TransitionRequest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    to_state: WorkItemState
    evidence_refs: tuple[str, ...] = ()
    review_ref: str | None = None
    effect_refs: tuple[str, ...] = ()
    readback_refs: tuple[str, ...] = ()


class LeaseRequest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    resource_id: str = Field(min_length=1, max_length=256)
    owner_attempt_id: str = Field(min_length=1, max_length=256)
    owner_runtime_id: str = Field(min_length=1, max_length=256)
    grant_ref: str = Field(min_length=1, max_length=256)
    authority_incarnation: str = Field(min_length=1, max_length=256)
    scope_id: str = Field(default="local-scope", min_length=1, max_length=256)
    mode: Literal["exclusive", "shared"] = "exclusive"
    work_item_id: str | None = Field(default=None, max_length=256)
    ttl_seconds: int = Field(gt=0, le=3600)


class ArtifactRef(BaseModel):
    """Immutable reference to bytes in an authorized artifact store."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    path: str = Field(min_length=1, max_length=1024)
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    size_bytes: int = Field(ge=0)
    media_type: str = Field(default="application/octet-stream", min_length=1, max_length=256)
    kind: Literal["source", "output", "test", "readback", "manifest", "other"] = "other"
    scope_id: str = Field(default="local-scope", min_length=1, max_length=256)
    immutable: bool = True

    @field_validator("path")
    @classmethod
    def relative_path(cls, value: str) -> str:
        if not value or "\x00" in value or any(ord(ch) < 0x20 for ch in value):
            raise ValueError("artifact path must be relative and NUL/control-free")
        if value.startswith(("/", "\\", "//", "\\\\")):
            raise ValueError("artifact path must be relative")
        if len(value) >= 2 and value[1] == ":":
            raise ValueError("drive/device paths are not allowed")
        if value.startswith(("\\\\?\\", "\\\\.\\", "\\??\\")):
            raise ValueError("device paths are not allowed")
        if ":" in value:
            raise ValueError("ADS/colon paths are not allowed")
        parts = value.replace("\\", "/").split("/")
        if any(part in ("", ".", "..") for part in parts):
            raise ValueError("artifact path contains traversal or empty segments")
        return "/".join(parts)


ArtifactReference = ArtifactRef


class ExecutionReceipt(BaseModel):
    """Typed execution facts; incomplete/unsupported observations stay candidates."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["acs-execution-receipt/1"] = "acs-execution-receipt/1"
    receipt_id: str = Field(min_length=1, max_length=256)
    work_item_id: str = Field(min_length=1, max_length=256)
    attempt_id: str = Field(min_length=1, max_length=256)
    runtime_id: str = Field(min_length=1, max_length=256)
    provider: str = Field(min_length=1, max_length=256)
    command_id: str = Field(min_length=1, max_length=256)
    operation_id: str = Field(min_length=1, max_length=256)
    event_id: str = Field(min_length=1, max_length=256)
    source_baseline: str = Field(min_length=1, max_length=512)
    candidate_ref: str = Field(min_length=1, max_length=512)
    source_commit: str = Field(min_length=1, max_length=256)
    source_tree: str = Field(min_length=1, max_length=256)
    source_diff: ArtifactRef | None = None
    untracked_manifest: ArtifactRef | None = None
    test_commands: tuple[str, ...] = ()
    test_exit_codes: tuple[int, ...] = ()
    test_exit_code: int | None = None
    os: str = Field(min_length=1, max_length=256)
    toolchain: str = Field(min_length=1, max_length=512)
    lockfile_digest: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    artifact_refs: tuple[ArtifactRef, ...] = ()
    readback_refs: tuple[ArtifactRef, ...] = ()
    source_sync: str = Field(min_length=1, max_length=256)
    usage: dict[str, Any] | None = None
    unresolved_items: tuple[str, ...] = ()
    status: Literal["succeeded", "failed", "cancelled", "uncertain", "unsupported", "incomplete"] = "incomplete"
    observed_at: datetime

    @property
    def is_complete(self) -> bool:
        return (
            self.status == "succeeded"
            and bool(self.source_baseline and self.candidate_ref and self.source_commit and self.source_tree)
            and bool(self.test_commands)
            and bool(self.test_exit_codes or self.test_exit_code is not None)
            and (not self.test_exit_codes or len(self.test_exit_codes) == len(self.test_commands))
            and all(code == 0 for code in self.test_exit_codes)
            and (self.test_exit_code is None or self.test_exit_code == 0)
            and bool(self.artifact_refs)
            and all(ref.immutable for ref in self.artifact_refs)
            and bool(self.source_sync)
            and not self.unresolved_items
        )


class EvidenceBundle(BaseModel):
    """Candidate output plus complete, source-bound execution facts."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["acs-evidence-bundle/1"] = "acs-evidence-bundle/1"
    evidence_id: str = Field(min_length=1, max_length=256)
    work_item_id: str = Field(min_length=1, max_length=256)
    source_baseline: str = Field(min_length=1, max_length=512)
    candidate_ref: str = Field(min_length=1, max_length=512)
    producer_ref: str = Field(min_length=1, max_length=256)
    observer_ref: str = Field(min_length=1, max_length=256)
    source_class: Literal["directly_verified", "endpoint_reported", "mocked", "not_run", "unsupported", "stale", "uncertain"]
    evidence_state: Literal["complete", "incomplete", "uncertain", "stale", "not_run"] = "incomplete"
    execution_receipt: ExecutionReceipt
    artifact_refs: tuple[ArtifactRef, ...] = ()
    readback_refs: tuple[ArtifactRef, ...] = ()
    command_id: str = Field(min_length=1, max_length=256)
    operation_id: str = Field(min_length=1, max_length=256)
    event_id: str = Field(min_length=1, max_length=256)
    observed_at: datetime
    expires_at: datetime | None = None
    unresolved_items: tuple[str, ...] = ()

    @property
    def is_complete(self) -> bool:
        return (
            self.source_class == "directly_verified"
            and self.evidence_state == "complete"
            and not self.unresolved_items
            and self.execution_receipt.source_baseline == self.source_baseline
            and self.execution_receipt.candidate_ref == self.candidate_ref
            and self.execution_receipt.is_complete
            and bool(self.artifact_refs or self.execution_receipt.artifact_refs)
        )


class EvidenceRecord(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    evidence_id: str = Field(min_length=1, max_length=256)
    work_item_id: str = Field(min_length=1, max_length=256)
    observer_ref: str = Field(min_length=1, max_length=256)
    source_class: Literal["directly_verified", "endpoint_reported", "mocked", "not_run"]
    baseline_ref: str = Field(min_length=1, max_length=256)
    artifact_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    summary: str = Field(min_length=1)
    # Optional for legacy records; readiness must require EvidenceBundle.
    bundle_ref: str | None = Field(default=None, max_length=512)
    candidate_ref: str | None = Field(default=None, max_length=512)
    execution_receipt_ref: str | None = Field(default=None, max_length=512)
    evidence_state: Literal["complete", "incomplete", "uncertain", "stale", "not_run"] = "incomplete"
    producer_ref: str | None = Field(default=None, max_length=256)
    attempt_id: str | None = Field(default=None, max_length=256)
    command_id: str | None = Field(default=None, max_length=256)
    operation_id: str | None = Field(default=None, max_length=256)
    event_id: str | None = Field(default=None, max_length=256)
    test_exit_code: int | None = None
    artifact_refs: tuple[ArtifactRef, ...] = ()
    readback_refs: tuple[ArtifactRef, ...] = ()


class EffectReadback(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    effect_id: str = Field(min_length=1, max_length=256)
    work_item_id: str = Field(min_length=1, max_length=256)
    resource_id: str = Field(min_length=1, max_length=256)
    status: Literal["verified"]
    readback_ref: str = Field(min_length=1, max_length=256)
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    size_bytes: int = Field(ge=0, strict=True)
    operation_id: str = Field(min_length=1, max_length=256)
    intent_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    completion_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    completion_state: Literal["completed"]
