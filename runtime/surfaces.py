from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any, Literal

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, JsonValue, ValidationError, field_validator
from pydantic_core import to_jsonable_python

from runtime.auth import LocalCredentialAuthenticator, LocalCredentialUnavailable
from runtime.delivery import DeliveryRejected
from runtime.delivery_models import DeliveryPacket, EndpointBindingRequest
from runtime.delivery_operations import DeliveryOperations
from runtime.domain import DomainAuthority
from runtime.enrollment_models import (
    AttemptRegistration,
    NodeChallengeRequest,
    NodeCommandProof,
    NodeEnrollment,
    NodeRevocation,
    NodeRotation,
    RuntimeRegistration,
)
from runtime.errors import (
    AcceptanceGuardFailed,
    AuthorizationDenied,
    EffectUnavailable,
    FencingRejected,
    IdempotencyConflict,
    InvalidTransition,
    LeaseRejected,
    NotFound,
    RevisionConflict,
)
from runtime.json_payload import MAX_COMMAND_BYTES, bounded_payload
from runtime.models import (
    CommandEnvelope,
    EvidenceBundle,
    EvidenceRecord,
    ExecutionReceipt,
    LeaseRequest,
    TransitionRequest,
)


class SurfaceCommand(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    schema_version: Literal["1.0"] = "1.0"
    command_type: str = Field(min_length=1, max_length=128)
    target_id: str = Field(min_length=1, max_length=256)
    expected_revision: int = Field(ge=0, strict=True)
    command_id: str = Field(min_length=1, max_length=256)
    idempotency_key: str = Field(min_length=1, max_length=256)
    correlation_id: str = Field(min_length=1, max_length=256)
    causation_id: str | None = Field(default=None, max_length=256)
    target_kind: Literal["work_item", "message", "lease", "effect", "node", "runtime", "attempt"] = "work_item"
    issued_at: datetime
    deadline: datetime
    payload: dict[str, JsonValue] = Field(default_factory=dict)

    @field_validator("payload", mode="before")
    @classmethod
    def bounded_json(cls, value):
        return bounded_payload(value)

    @field_validator("issued_at", "deadline")
    @classmethod
    def timezone_required(cls, value):
        if value.tzinfo is None:
            raise ValueError("surface timestamps require a timezone")
        return value

    @field_validator("deadline")
    @classmethod
    def ordered_deadline(cls, value, info):
        if info.data.get("issued_at") is not None and value < info.data["issued_at"]:
            raise ValueError("deadline must not precede issued_at")
        return value

    def to_domain(self, context) -> CommandEnvelope:
        business_payload = dict(self.payload)
        if self.command_type in {"runtime.register", "attempt.register"}:
            business_payload.update(self.node_input())
            business_payload.pop("proof", None)
        elif self.command_type == "execution.record":
            business_payload.update(self.node_input())
            business_payload.pop("node_proof", None)
        return CommandEnvelope(
            command_id=self.command_id, command_type=self.command_type, idempotency_key=self.idempotency_key,
            correlation_id=self.correlation_id, causation_id=self.causation_id,
            tenant_id=context.tenant_id, authority_id=context.authority_id,
            authority_incarnation=context.authority_incarnation, principal_ref=context.principal_ref,
            grant_ref=context.grant_ref, target_kind=self.target_kind, target_id=self.target_id,
            expected_revision=self.expected_revision, issued_at=self.issued_at, deadline=self.deadline,
            payload=business_payload,
        )

    def node_input(self):
        """Typed canonical input for EnrollmentAuthority.signing_hash."""
        if self.command_type == "execution.record":
            model, key = ExecutionReceipt, "receipt"
        elif self.command_type in {"runtime.register", "attempt.register"}:
            model = RuntimeRegistration if self.command_type == "runtime.register" else AttemptRegistration
            key = "request"
        else:
            raise ValueError("this command does not use a Node proof")
        value = model.model_validate_json(json.dumps(self.payload[key]), strict=True)
        return {key: value.model_dump(mode="json")}


class SurfaceError(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    code: str
    message: str


class SurfaceReply(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    schema_version: Literal["acs-surface-result/1"] = "acs-surface-result/1"
    ok: bool
    result: JsonValue = None
    error: SurfaceError | None = None


ERRORS = {
    "UNAUTHENTICATED": (401, "A valid transport credential is required."),
    "AUTHORIZATION_DENIED": (403, "The configured role is not authorized for this action."),
    "INPUT_INVALID": (422, "The command does not match the accepted schema or limits."),
    "NOT_FOUND": (404, "The requested object is unavailable."),
    "IDEMPOTENCY_CONFLICT": (409, "This command identity is bound to different input."),
    "REVISION_CONFLICT": (409, "The expected revision does not match."),
    "GUARD_REJECTED": (409, "The command did not satisfy its Domain preconditions."),
    "SERVICE_UNAVAILABLE": (503, "The command could not be completed. Its committed identity may be retried."),
    "CONFIGURATION_INVALID": (500, "The trusted surface configuration is unavailable or invalid."),
}


def failure(code):
    return SurfaceReply(ok=False, error=SurfaceError(code=code, message=ERRORS[code][1]))


class PayloadModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class WorkCreate(PayloadModel):
    scope_id: str = "local-scope"
    agent_slot_id: str = "local-slot"
    source_baseline: str = "baseline"
    # Accepted by the original flat prototype; the authoritative key is outer.
    idempotency_key: str | None = None


class WorkTransition(TransitionRequest):
    @field_validator("evidence_refs", "effect_refs", "readback_refs", mode="before")
    @classmethod
    def legacy_refs(cls, value):
        if isinstance(value, str):
            return tuple(value.split(",")) if value else ()
        return tuple(value) if isinstance(value, list) else value


class EvidencePayload(PayloadModel):
    evidence: EvidenceRecord
    bundle: EvidenceBundle | None = None


class ExecutionPayload(PayloadModel):
    receipt: ExecutionReceipt
    node_proof: NodeCommandProof


class ReviewAssignment(PayloadModel):
    reviewer_ref: str
    reviewer_grant_ref: str


class ReviewPayload(PayloadModel):
    review_id: str
    verdict: Literal["pass", "fail"]
    evidence_ref: str
    baseline_ref: str


class EffectRegistration(PayloadModel):
    effect_id: str
    lease_id: str
    resource_id: str
    readback_ref: str
    operation_id: str


class EffectReconciliation(PayloadModel):
    effect_id: str


class RuntimePayload(PayloadModel):
    request: RuntimeRegistration
    proof: NodeCommandProof


class AttemptPayload(PayloadModel):
    request: AttemptRegistration
    proof: NodeCommandProof


class LeasePayload(PayloadModel):
    lease_id: str
    resource_id: str
    generation: int = Field(ge=1, strict=True)
    fencing_token: str


class LeaseRenew(LeasePayload):
    ttl_seconds: int = Field(ge=1, le=3600, strict=True)


class MessageSend(PayloadModel):
    packet: DeliveryPacket
    endpoint_id: str = Field(min_length=1, max_length=256)
    binding_revision: int = Field(ge=1, strict=True)


class DeliveryScan(PayloadModel):
    scope_id: str = Field(min_length=1, max_length=256)
    limit: int = Field(default=16, ge=1, le=64, strict=True)


class DeliveryDispatch(PayloadModel):
    operation_id: str = Field(min_length=1, max_length=256)


PAYLOADS = {
    "work_item.create": WorkCreate, "work_item.transition": WorkTransition,
    "evidence.record": EvidencePayload, "execution.record": ExecutionPayload,
    "review.assign": ReviewAssignment, "review.record": ReviewPayload,
    "effect.register": EffectRegistration, "effect.reconcile": EffectReconciliation,
    "node.enroll": NodeEnrollment, "node.rotate": NodeRotation, "node.revoke": NodeRevocation,
    "node.challenge": NodeChallengeRequest, "runtime.register": RuntimePayload, "attempt.register": AttemptPayload,
    "lease.acquire": LeaseRequest, "lease.renew": LeaseRenew, "lease.release": LeasePayload, "lease.revoke": LeasePayload,
    "work_item.read": PayloadModel,
    "message.bind": EndpointBindingRequest, "message.send": MessageSend, "message.read": PayloadModel,
    "delivery.scan": DeliveryScan, "delivery.dispatch": DeliveryDispatch,
}


class SharedService:
    def __init__(self, authority: DomainAuthority, authenticator: LocalCredentialAuthenticator | None = None):
        self.authority, self.authenticator = authority, authenticator
        self.delivery_operations = DeliveryOperations(authority)

    def authenticate(self, credential):
        if self.authenticator is None:
            raise PermissionError("transport authentication is unavailable")
        try:
            context = self.authenticator.authenticate(credential)
        except LocalCredentialUnavailable:
            raise PermissionError("transport authentication failed") from None
        if context != self.authority.context:
            raise PermissionError("transport role binding differs")

    def command(self, request: SurfaceCommand, credential: str | None = None):
        self.authenticate(credential)
        request = SurfaceCommand.model_validate_json(request.model_dump_json(), strict=True)
        if credential and credential in request.model_dump_json():
            raise ValueError("credentials are not command input")
        if request.command_type not in PAYLOADS:
            raise ValueError("unsupported command")
        raw = request.payload
        if request.command_type == "evidence.record" and "evidence" not in raw:
            raw = {"evidence": raw}
        payload = PAYLOADS[request.command_type].model_validate_json(json.dumps(raw), strict=True)
        envelope = request.to_domain(self.authority.context)
        authority, name = self.authority, request.command_type
        if name == "work_item.create":
            result = authority.create_work_item(envelope, payload.scope_id, payload.agent_slot_id, payload.source_baseline)
        elif name == "work_item.transition":
            result = authority.transition_work_item(envelope, payload)
        elif name == "evidence.record":
            result = authority.record_evidence(envelope, payload.evidence, payload.bundle)
        elif name == "execution.record":
            result = authority.record_execution_receipt(envelope, payload.receipt, node_proof=payload.node_proof)
        elif name == "review.assign":
            result = authority.assign_reviewer(envelope, request.target_id, payload.reviewer_ref, payload.reviewer_grant_ref)
        elif name == "review.record":
            result = authority.record_review(envelope, payload.review_id, request.target_id, payload.verdict, payload.evidence_ref, payload.baseline_ref)
        elif name in {"effect.register", "effect.reconcile"}:
            method = authority.register_effect if name == "effect.register" else authority.reconcile_effect
            result = method(envelope, **payload.model_dump())
        elif name in {"node.enroll", "node.rotate", "node.revoke", "node.challenge"}:
            method = {"node.enroll": authority.enroll_node, "node.rotate": authority.rotate_node,
                      "node.revoke": authority.revoke_node, "node.challenge": authority.challenge_node}[name]
            result = method(envelope, payload)
        elif name in {"runtime.register", "attempt.register"}:
            method = authority.register_runtime if name == "runtime.register" else authority.register_attempt
            result = method(envelope, payload.request, payload.proof)
        elif name == "lease.acquire":
            result = authority.leases.acquire_lease(envelope, payload)
        elif name.startswith("lease."):
            method = {"lease.renew": authority.leases.renew_lease, "lease.release": authority.leases.release_lease,
                      "lease.revoke": authority.leases.revoke_lease}[name]
            result = method(envelope, **payload.model_dump())
        elif name == "message.bind":
            result = authority.bind_message_endpoint(envelope, payload)
        elif name == "message.send":
            result = authority.send_message(envelope, payload.packet, endpoint_id=payload.endpoint_id,
                                            binding_revision=payload.binding_revision)
        elif name == "message.read":
            result = authority.read_message(envelope, request.target_id)
        elif name == "delivery.scan":
            result = self.delivery_operations.scan(envelope, **payload.model_dump())
        elif name == "delivery.dispatch":
            result = self.delivery_operations.dispatch(envelope, **payload.model_dump())
        else:
            if envelope.deadline <= datetime.now(UTC) or envelope.issued_at > datetime.now(UTC):
                raise AuthorizationDenied(envelope.principal_ref, envelope.grant_ref)
            result = authority.get_work_item(request.target_id)
            if result is None:
                raise NotFound("work_item", request.target_id)
        return result.model_dump(mode="json") if isinstance(result, BaseModel) else to_jsonable_python(result)

    def handle(self, raw: Any, credential: str | None = None) -> SurfaceReply:
        try:
            self.authenticate(credential)
            request = raw if isinstance(raw, SurfaceCommand) else SurfaceCommand.model_validate_json(json.dumps(raw), strict=True)
            reply = SurfaceReply(ok=True, result=self.command(request, credential))
            if credential and credential in reply.model_dump_json():
                return failure("SERVICE_UNAVAILABLE")
            return reply
        except PermissionError:
            return failure("UNAUTHENTICATED")
        except AuthorizationDenied:
            return failure("AUTHORIZATION_DENIED")
        except IdempotencyConflict:
            return failure("IDEMPOTENCY_CONFLICT")
        except RevisionConflict:
            return failure("REVISION_CONFLICT")
        except (NotFound, KeyError):
            return failure("NOT_FOUND")
        except (ValidationError, ValueError, TypeError, RecursionError):
            return failure("INPUT_INVALID")
        except (AcceptanceGuardFailed, InvalidTransition, LeaseRejected, FencingRejected, EffectUnavailable, DeliveryRejected):
            return failure("GUARD_REJECTED")
        except Exception:  # noqa: BLE001 - transport boundary must not expose private backend exception text
            # Never return raw database exceptions, private references or input.
            return failure("SERVICE_UNAVAILABLE")


def create_app(service: SharedService) -> FastAPI:
    app = FastAPI(title="Agent Collaboration Runtime", version="1", debug=False)

    @app.exception_handler(RequestValidationError)
    async def invalid_request(_request, _error):
        return JSONResponse(failure("INPUT_INVALID").model_dump(mode="json"), status_code=422)

    @app.get("/v1/health")
    def health():
        return {"api_version": "1", "status": "listening"}

    @app.get("/v1/schema")
    def schema():
        return {"command": SurfaceCommand.model_json_schema(),
                "payloads": {name: model.model_json_schema() for name, model in PAYLOADS.items()},
                "response": SurfaceReply.model_json_schema()}

    @app.post("/v1/commands", response_model=SurfaceReply)
    async def submit(request: Request):
        credential = request.headers.get("x-acs-credential")
        try:
            service.authenticate(credential)
        except PermissionError:
            return JSONResponse(failure("UNAUTHENTICATED").model_dump(mode="json"), status_code=401)
        data = bytearray()
        async for chunk in request.stream():
            data.extend(chunk)
            if len(data) > MAX_COMMAND_BYTES:
                return JSONResponse(failure("INPUT_INVALID").model_dump(mode="json"), status_code=422)
        try:
            raw = json.loads(data)
        except (ValueError, UnicodeError):
            raw = None
        # The synchronous Domain transaction is shielded from HTTP cancellation
        # by its worker; no disconnect is interpreted as a business cancellation.
        from starlette.concurrency import run_in_threadpool
        reply = await run_in_threadpool(service.handle, raw, credential)
        status = 200 if reply.ok else ERRORS[reply.error.code][0]
        return JSONResponse(reply.model_dump(mode="json"), status_code=status)

    return app
