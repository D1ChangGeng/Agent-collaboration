from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator


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


type PayloadValue = str | int | bool | None | tuple[str, ...]


class CommandEnvelope(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["1.0"] = "1.0"
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
    target_kind: Literal["work_item", "message", "lease", "effect"]
    target_id: str = Field(min_length=1, max_length=256)
    expected_revision: int = Field(ge=0)
    issued_at: datetime
    deadline: datetime
    payload: dict[str, PayloadValue] = Field(default_factory=dict)

    @field_validator("deadline")
    @classmethod
    def deadline_after_issue(cls, value: datetime, info: ValidationInfo) -> datetime:
        issued_at = info.data.get("issued_at")
        if isinstance(issued_at, datetime) and value < issued_at:
            raise ValueError("deadline must not precede issued_at")
        return value


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
    ttl_seconds: int = Field(gt=0, le=3600)


class EvidenceRecord(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    evidence_id: str = Field(min_length=1, max_length=256)
    work_item_id: str = Field(min_length=1, max_length=256)
    observer_ref: str = Field(min_length=1, max_length=256)
    source_class: Literal["directly_verified", "endpoint_reported", "mocked", "not_run"]
    baseline_ref: str = Field(min_length=1, max_length=256)
    artifact_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    summary: str = Field(min_length=1)


class EffectReadback(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    effect_id: str = Field(min_length=1, max_length=256)
    work_item_id: str = Field(min_length=1, max_length=256)
    resource_id: str = Field(min_length=1, max_length=256)
    status: Literal["verified"]
    readback_ref: str = Field(min_length=1, max_length=256)
