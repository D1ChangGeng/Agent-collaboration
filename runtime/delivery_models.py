from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, field_validator

# Signed cross-host observation includes authorization and receipt persistence.
# The receiver independently refreshes its shorter local lease before invoking.
TRANSPORT_READINESS_SECONDS = 15


class DeliveryModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class DeliveryPacket(DeliveryModel):
    schema_version: Literal["acs-delivery/1"] = "acs-delivery/1"
    work_item_id: str = Field(min_length=1, max_length=256)
    target_scope_id: str = Field(min_length=1, max_length=256)
    target_agent_slot_id: str = Field(min_length=1, max_length=256)
    accepted_revision: int = Field(ge=0, strict=True)
    goal: str = Field(min_length=1, max_length=2048)
    accepted_state_summary: str = Field(min_length=1, max_length=4096)
    request: str = Field(min_length=1, max_length=8192)
    constraints: tuple[str, ...] = Field(default=(), max_length=32)
    source_baseline: str | None = Field(default=None, min_length=1, max_length=512)
    context_digests: tuple[str, ...] = Field(default=(), max_length=32)
    expected_response: str = Field(min_length=1, max_length=4096)
    required_evidence: tuple[str, ...] = Field(default=(), max_length=32)
    activation: Literal["message_only", "invoke"] = "message_only"
    delivery_policy: Literal["immediate", "queue_until_idle"] = "immediate"
    deadline: datetime | None = None
    maximum_attempts: int = Field(default=3, ge=1, le=8, strict=True)
    retry_delay_seconds: int = Field(default=1, ge=1, le=30, strict=True)

    @field_validator("deadline")
    @classmethod
    def timezone_required(cls, value):
        if value is None:
            return value
        if value.tzinfo is None:
            raise ValueError("delivery deadline requires timezone")
        return value

    @field_validator("constraints", "required_evidence")
    @classmethod
    def bounded_texts(cls, values):
        if any(not item or len(item) > 1024 for item in values):
            raise ValueError("packet list entries must be bounded nonempty text")
        return values

    @field_validator("context_digests")
    @classmethod
    def digests(cls, values):
        if any(len(value) != 64 or any(c not in "0123456789abcdef" for c in value) for value in values):
            raise ValueError("context digests must be lowercase SHA-256")
        return values


class MessagePacket(DeliveryModel):
    """An authenticated natural message, independent of the retired work domain."""

    schema_version: Literal["acs-message/1"] = "acs-message/1"
    project_id: str = Field(min_length=1, max_length=128)
    sender: str = Field(min_length=1, max_length=512)
    recipient: str = Field(min_length=1, max_length=512)
    content: str = Field(min_length=1, max_length=32768)
    reply_to: tuple[str, ...] = Field(default=(), max_length=32)
    response_mode: Literal["async", "sync"] = "async"
    target_scope_id: str = Field(min_length=1, max_length=256)
    target_agent_slot_id: str | None = Field(default=None, min_length=1, max_length=256)
    activation: Literal["message_only", "invoke"] = "invoke"
    delivery_policy: Literal["queue_until_idle"] = "queue_until_idle"
    deadline: datetime | None = None
    maximum_attempts: int = Field(default=3, ge=1, le=8, strict=True)
    retry_delay_seconds: int = Field(default=1, ge=1, le=30, strict=True)

    @field_validator("content")
    @classmethod
    def nonempty(cls, value):
        if not value.strip():
            raise ValueError("message content must not be blank")
        return value

    @field_validator("deadline")
    @classmethod
    def aware_deadline(cls, value):
        return DeliveryPacket.timezone_required(value)


class NoticePacket(DeliveryModel):
    """Internal ACS notification; never indexed as an Agent message or reply."""

    schema_version: Literal["acs-notice/1"] = "acs-notice/1"
    project_id: str = Field(min_length=1, max_length=128)
    sender: Literal["acs"] = "acs"
    recipient: str = Field(min_length=1, max_length=512)
    content: str = Field(min_length=1, max_length=8192)
    origin_message_id: str = Field(min_length=1, max_length=256)
    notification_sequence: int = Field(ge=1, strict=True)
    target_scope_id: str = Field(min_length=1, max_length=256)
    target_agent_slot_id: str = Field(min_length=1, max_length=256)
    activation: Literal["invoke"] = "invoke"
    delivery_policy: Literal["queue_until_idle"] = "queue_until_idle"
    deadline: datetime | None = None
    maximum_attempts: int = Field(default=3, ge=1, le=8, strict=True)
    retry_delay_seconds: int = Field(default=1, ge=1, le=30, strict=True)

    @field_validator("deadline")
    @classmethod
    def aware_deadline(cls, value):
        return DeliveryPacket.timezone_required(value)


Packet = Annotated[DeliveryPacket | MessagePacket | NoticePacket, Field(discriminator="schema_version")]
PACKET = TypeAdapter(Packet)


class EndpointBindingRequest(DeliveryModel):
    scope_id: str = Field(min_length=1, max_length=256)
    agent_slot_id: str = Field(min_length=1, max_length=256)
    expires_at: datetime | None = None

    @field_validator("expires_at")
    @classmethod
    def timezone_required(cls, value):
        if value is None:
            return value
        if value.tzinfo is None:
            raise ValueError("binding expiry requires timezone")
        return value


class EndpointResolutionRequest(DeliveryModel):
    tenant_id: str = Field(min_length=1, max_length=256)
    message_id: str = Field(min_length=1, max_length=256)
    operation_id: str = Field(min_length=1, max_length=256)
    attempt_id: str = Field(min_length=1, max_length=512)
    dispatch_id: str = Field(min_length=1, max_length=512)
    failed_endpoint_id: str = Field(min_length=1, max_length=256)
    failed_binding_revision: int = Field(ge=1, strict=True)
    target_scope_id: str = Field(min_length=1, max_length=256)
    target_agent_slot_id: str = Field(min_length=1, max_length=256)
    activation: Literal["message_only", "invoke"]
    failure_code: Literal["native_pre_call_rejected"]


class EndpointResolution(DeliveryModel):
    endpoint_id: str = Field(min_length=1, max_length=256)
    binding_revision: int = Field(ge=1, strict=True)
    resolver_id: str = Field(min_length=1, max_length=256)
    resolver_revision: int = Field(ge=1, strict=True)
    reason: str = Field(min_length=1, max_length=1024)


class DeliveryEnvelope(DeliveryModel):
    tenant_id: str
    authority_id: str = Field(min_length=1, max_length=256)
    authority_incarnation: str = Field(min_length=1, max_length=256)
    principal_ref: str = Field(min_length=1, max_length=256)
    grant_ref: str = Field(min_length=1, max_length=256)
    message_id: str
    command_id: str
    operation_id: str
    endpoint_id: str | None
    binding_revision: int | None
    machine_id: str | None
    node_id: str | None
    boot_incarnation: str | None
    accepted_state_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    packet: Packet


class InvocationRequest(DeliveryModel):
    """Immutable call identity prepared before crossing the native boundary."""

    schema_version: Literal["acs-invocation/1"] = "acs-invocation/1"
    invocation_id: str = Field(min_length=1, max_length=512)
    attempt_id: str = Field(min_length=1, max_length=512)
    dispatch_id: str = Field(min_length=1, max_length=512)
    runtime_dispatched_receipt_id: str = Field(min_length=1, max_length=512)
    message_id: str = Field(min_length=1, max_length=256)
    command_id: str = Field(min_length=1, max_length=256)
    operation_id: str = Field(min_length=1, max_length=256)
    envelope_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    logical_payload_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    selection_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    accepted_revision: int | None = Field(default=None, ge=0, strict=True)
    accepted_state_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    envelope: DeliveryEnvelope


class InvocationObservation(DeliveryModel):
    """A Driver's explicit observation; this module never fabricates native ACKs."""

    invocation_id: str = Field(min_length=1, max_length=512)
    dispatch_id: str = Field(min_length=1, max_length=512)
    runtime_dispatched_receipt_id: str = Field(min_length=1, max_length=512)
    native_dispatch_ref: str = Field(min_length=1, max_length=512)
    native_ack_ref: str | None = Field(default=None, min_length=1, max_length=512)
    response_ref: str | None = Field(default=None, min_length=1, max_length=512)
    response: dict[str, Any] | None = None


TERMINAL_STATES = frozenset({"delivered", "uncertain", "expired", "blocked", "budget_exhausted"})
