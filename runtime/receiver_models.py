from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

Hex64 = str


class FrozenModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class EndpointRegistration(FrozenModel):
    schema_version: Literal["acs-endpoint-registration/1"] = "acs-endpoint-registration/1"
    purpose: Literal["endpoint.register"] = "endpoint.register"
    registration_id: str = Field(min_length=1, max_length=256)
    endpoint_id: str = Field(min_length=1, max_length=256)
    endpoint_revision: int = Field(ge=1, strict=True)
    connection_ref: str = Field(min_length=1, max_length=256)
    tenant_id: str
    authority_id: str
    authority_incarnation: str
    node_id: str
    node_binding_revision: int = Field(ge=1, strict=True)
    runtime_id: str
    runtime_revision: int = Field(ge=1, strict=True)
    machine_id: str
    boot_incarnation: str
    scope_id: str
    agent_slot_id: str
    tls_certificate_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    config_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    expires_at: datetime

    @field_validator("expires_at")
    @classmethod
    def timezone_required(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("registration expiry requires timezone")
        return value.astimezone(UTC)


class EndpointBinding(FrozenModel):
    registration: EndpointRegistration
    locator_host: str
    locator_port: int = Field(ge=1, le=65535, strict=True)
    route_class: Literal["loopback", "private", "tunnel"]
    node_key_id: str
    node_public_key: str = Field(pattern=r"^[a-f0-9]{64}$")
    registration_signature: str = Field(pattern=r"^[a-f0-9]{128}$")


class DeliveryAdmission(FrozenModel):
    schema_version: Literal["acs-delivery-admission/1"] = "acs-delivery-admission/1"
    purpose: Literal["delivery.prepare", "delivery.dispatch", "delivery.readback", "delivery.recover"]
    authority_key_id: str
    authority_key_revision: int = Field(ge=1, strict=True)
    tenant_id: str
    authority_id: str
    authority_incarnation: str
    request_id: str
    nonce: str = Field(pattern=r"^[a-f0-9]{64}$")
    method: Literal["POST"] = "POST"
    path: str
    body_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    message_id: str
    command_id: str
    operation_id: str
    attempt_id: str
    dispatch_id: str
    endpoint_id: str
    endpoint_revision: int = Field(ge=1, strict=True)
    runtime_id: str
    runtime_revision: int = Field(ge=1, strict=True)
    node_id: str
    machine_id: str
    boot_incarnation: str
    scope_id: str
    agent_slot_id: str
    accepted_revision: int = Field(ge=0, strict=True)
    accepted_state_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    envelope_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    selection_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    invocation_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    journal_generation: int = Field(ge=1, strict=True)
    issued_at: datetime
    deadline: datetime

    @field_validator("issued_at", "deadline")
    @classmethod
    def timezone_required(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("admission timestamps require timezone")
        return value.astimezone(UTC)


class PrepareBody(FrozenModel):
    envelope: dict[str, Any]
    invocation: dict[str, Any]
    selection: dict[str, Any]


class DispatchBody(FrozenModel):
    prepare_request_id: str
    marker_receipt_id: str


class ReadbackBody(FrozenModel):
    operation_id: str
    dispatch_id: str


class RecoveryBody(FrozenModel):
    prepare_request_id: str
    marker_receipt_id: str
    old_boot_incarnation: str
    new_boot_incarnation: str
    journal_generation: int = Field(ge=2, strict=True)
    old_boot_isolation_ref: str = Field(min_length=1, max_length=512)
    old_endpoint_revision: int = Field(ge=1, strict=True)
    new_endpoint_revision: int = Field(ge=1, strict=True)
    old_runtime_revision: int = Field(ge=1, strict=True)
    new_runtime_revision: int = Field(ge=1, strict=True)


class SignedRequest(FrozenModel):
    admission: DeliveryAdmission
    body: dict[str, Any]
    signature: str = Field(pattern=r"^[a-f0-9]{128}$")


class ReceiverReceipt(FrozenModel):
    schema_version: Literal["acs-receiver-receipt/1"] = "acs-receiver-receipt/1"
    receipt_id: str
    request_id: str
    challenge_nonce: str = Field(pattern=r"^[a-f0-9]{64}$")
    purpose: str
    state: Literal["prepared", "runtime_dispatched", "runtime_acknowledged", "uncertain", "blocked", "readback"]
    target_request_id: str
    readback_request_id: str | None = None
    tenant_id: str
    authority_id: str
    authority_incarnation: str
    message_id: str
    command_id: str
    operation_id: str
    attempt_id: str
    dispatch_id: str
    endpoint_id: str
    endpoint_revision: int
    runtime_id: str
    runtime_revision: int
    node_id: str
    node_binding_revision: int
    machine_id: str
    boot_incarnation: str
    scope_id: str
    agent_slot_id: str
    accepted_revision: int
    accepted_state_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    envelope_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    selection_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    invocation_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    journal_generation: int
    request_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    evidence: dict[str, Any] = Field(default_factory=dict)
    observed_at: datetime


class SignedReceipt(FrozenModel):
    receipt: ReceiverReceipt
    node_key_id: str
    signature: str = Field(pattern=r"^[a-f0-9]{128}$")
