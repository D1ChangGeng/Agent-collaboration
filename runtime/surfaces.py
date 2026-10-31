from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Literal

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, JsonValue, ValidationError, field_validator
from pydantic_core import to_jsonable_python

from runtime.auth import LocalCredentialAuthenticator, LocalCredentialUnavailable
from runtime.delivery import DeliveryRejected
from runtime.delivery_models import EndpointBindingRequest
from runtime.delivery_operations import DeliveryOperations
from runtime.domain import DomainAuthority
from runtime.enrollment_models import (
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
)
from runtime.receiver_domain import (
    AuthorityTransportKeyRegistration,
    ConnectionReferenceRegistration,
    EndpointRegistrationCommand,
)
from runtime.recovery_models import BoundaryRejected, StateConflict


class SurfaceCommand(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    schema_version: Literal["1.0"] = "1.0"
    command_type: Literal[
        "node.enroll", "node.rotate", "node.revoke", "node.challenge", "runtime.register",
        "message.bind", "message.read", "delivery.scan", "delivery.dispatch",
        "receiver.key.register", "receiver.connection.register", "endpoint.register",
    ]
    target_id: str = Field(min_length=1, max_length=256)
    expected_revision: int = Field(ge=0, strict=True)
    command_id: str = Field(min_length=1, max_length=256)
    idempotency_key: str = Field(min_length=1, max_length=256)
    correlation_id: str = Field(min_length=1, max_length=256)
    causation_id: str | None = Field(default=None, max_length=256)
    target_kind: Literal[
        "message", "node", "runtime", "authority_transport_key", "connection", "endpoint",
    ] = "message"
    issued_at: datetime
    deadline: datetime | None = None
    payload: dict[str, JsonValue] = Field(default_factory=dict)

    @field_validator("payload", mode="before")
    @classmethod
    def bounded_json(cls, value):
        return bounded_payload(value)

    @field_validator("issued_at", "deadline")
    @classmethod
    def timezone_required(cls, value):
        if value is None:
            return value
        if value.tzinfo is None:
            raise ValueError("surface timestamps require a timezone")
        return value

    @field_validator("deadline")
    @classmethod
    def ordered_deadline(cls, value, info):
        if value is not None and info.data.get("issued_at") is not None and value < info.data["issued_at"]:
            raise ValueError("deadline must not precede issued_at")
        return value

    def to_domain(self, context) -> CommandEnvelope:
        business_payload = dict(self.payload)
        if self.command_type in {"runtime.register", "endpoint.register"}:
            business_payload.update(self.node_input())
            business_payload.pop("proof", None)
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
        if self.command_type == "runtime.register":
            model, key = RuntimeRegistration, "request"
        elif self.command_type == "endpoint.register":
            value = EndpointRegistrationCommand.model_validate_json(
                json.dumps(self.payload), strict=True,
            )
            return {
                "registration": value.registration.model_dump(mode="json"),
                "registration_signature": value.registration_signature,
            }
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


class RuntimePayload(PayloadModel):
    request: RuntimeRegistration
    proof: NodeCommandProof | None = None


class DeliveryScan(PayloadModel):
    scope_id: str = Field(min_length=1, max_length=256)
    limit: int = Field(default=16, ge=1, le=64, strict=True)


class DeliveryDispatch(PayloadModel):
    operation_id: str = Field(min_length=1, max_length=256)


PAYLOADS = {
    "node.enroll": NodeEnrollment, "node.rotate": NodeRotation, "node.revoke": NodeRevocation,
    "node.challenge": NodeChallengeRequest, "runtime.register": RuntimePayload,
    "message.bind": EndpointBindingRequest, "message.read": PayloadModel,
    "delivery.scan": DeliveryScan, "delivery.dispatch": DeliveryDispatch,
    "receiver.key.register": AuthorityTransportKeyRegistration,
    "receiver.connection.register": ConnectionReferenceRegistration,
    "endpoint.register": EndpointRegistrationCommand,
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
        payload = PAYLOADS[request.command_type].model_validate_json(json.dumps(request.payload), strict=True)
        envelope = request.to_domain(self.authority.context)
        authority, name = self.authority, request.command_type
        if name in {"node.enroll", "node.rotate", "node.revoke", "node.challenge"}:
            method = {"node.enroll": authority.enroll_node, "node.rotate": authority.rotate_node,
                      "node.revoke": authority.revoke_node, "node.challenge": authority.challenge_node}[name]
            result = method(envelope, payload)
        elif name == "runtime.register":
            result = authority.register_runtime(envelope, payload.request, payload.proof)
        elif name == "receiver.key.register":
            result = authority.register_authority_transport_key(envelope, payload)
        elif name == "receiver.connection.register":
            result = authority.register_receiver_connection(envelope, payload)
        elif name == "endpoint.register":
            result = authority.register_receiver_endpoint(envelope, payload)
        elif name == "message.bind":
            result = authority.bind_message_endpoint(envelope, payload)
        elif name == "message.read":
            result = authority.read_message(envelope, request.target_id)
        elif name == "delivery.scan":
            result = self.delivery_operations.scan(envelope, **payload.model_dump())
        elif name == "delivery.dispatch":
            result = self.delivery_operations.dispatch(envelope, **payload.model_dump())
        else:
            raise ValueError("unsupported command")
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
        except (IdempotencyConflict, StateConflict):
            return failure("IDEMPOTENCY_CONFLICT")
        except RevisionConflict:
            return failure("REVISION_CONFLICT")
        except (NotFound, KeyError):
            return failure("NOT_FOUND")
        except (ValidationError, ValueError, TypeError, RecursionError):
            return failure("INPUT_INVALID")
        except (AcceptanceGuardFailed, InvalidTransition, LeaseRejected, FencingRejected,
                EffectUnavailable, DeliveryRejected, BoundaryRejected):
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
