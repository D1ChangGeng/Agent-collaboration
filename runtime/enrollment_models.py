from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from runtime.models import CommandResult


class EnrollmentInput(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class NodeEnrollment(EnrollmentInput):
    scope_id: str = Field(min_length=1, max_length=256)
    agent_slot_id: str = Field(min_length=1, max_length=256)
    observer_grant_ref: str = Field(min_length=1, max_length=256)
    machine_id: str = Field(min_length=1, max_length=256)
    boot_incarnation: str = Field(min_length=1, max_length=256)
    public_key: str = Field(pattern=r"^[a-f0-9]{64}$")
    expires_at: datetime


class NodeRotation(EnrollmentInput):
    machine_id: str = Field(min_length=1, max_length=256)
    boot_incarnation: str = Field(min_length=1, max_length=256)
    public_key: str = Field(pattern=r"^[a-f0-9]{64}$")
    expires_at: datetime


class NodeRevocation(EnrollmentInput):
    reason: str = Field(min_length=1, max_length=1024)


class NodeChallengeRequest(EnrollmentInput):
    purpose: Literal[
        "runtime.register",
        "attempt.register",
        "execution.record",
        "endpoint.register",
        "delivery.prepare",
        "delivery.dispatch",
        "delivery.readback",
        "delivery.recover",
    ]
    purpose_command_id: str = Field(min_length=1, max_length=256)
    purpose_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    ttl_seconds: int = Field(default=120, ge=1, le=300, strict=True)


class NodeCommandProof(EnrollmentInput):
    challenge_id: str = Field(min_length=1, max_length=256)
    signature: str = Field(pattern=r"^[a-f0-9]{128}$")


class RuntimeRegistration(EnrollmentInput):
    node_id: str = Field(min_length=1, max_length=256)
    node_binding_revision: int = Field(ge=1, strict=True)
    provider: str = Field(min_length=1, max_length=256)
    producer_grant_ref: str = Field(min_length=1, max_length=256)
    expires_at: datetime


class AttemptRegistration(EnrollmentInput):
    runtime_id: str = Field(min_length=1, max_length=256)
    work_item_id: str = Field(min_length=1, max_length=256)
    expected_work_item_revision: int = Field(ge=0, strict=True)
    source_baseline: str = Field(min_length=1, max_length=512)
    source_commit: str = Field(min_length=1, max_length=256)
    source_tree: str = Field(min_length=1, max_length=256)
    candidate_ref: str = Field(min_length=1, max_length=512)
    observed_started_at: datetime


class EnrollmentReply(EnrollmentInput):
    result: CommandResult
    binding: dict[str, Any]


class NodeChallengeReply(EnrollmentInput):
    result: CommandResult
    challenge_id: str
    message_hex: str
    expires_at: datetime
