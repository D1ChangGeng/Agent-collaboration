from __future__ import annotations

import json
import uuid
from datetime import datetime
from typing import Literal

import typer
from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator

from runtime.auth import LocalCredentialAuthenticator, LocalCredentialUnavailable
from runtime.domain import DomainAuthority
from runtime.errors import RuntimeErrorBase
from runtime.models import (
    CommandEnvelope,
    EvidenceRecord,
    PayloadValue,
    TransitionRequest,
    WorkItemState,
)


class SurfaceCommand(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    command_type: str = Field(min_length=1, max_length=128)
    target_id: str = Field(min_length=1, max_length=256)
    expected_revision: int = Field(ge=0)
    command_id: str = Field(min_length=1, max_length=256)
    idempotency_key: str = Field(min_length=1, max_length=256)
    correlation_id: str = Field(min_length=1, max_length=256)
    causation_id: str | None = Field(default=None, max_length=256)
    target_kind: Literal["work_item", "message", "lease", "effect"] = "work_item"
    issued_at: datetime
    deadline: datetime
    payload: dict[str, PayloadValue] = Field(default_factory=dict)

    @field_validator("issued_at", "deadline")
    @classmethod
    def timezone_required(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("surface timestamps must include timezone")
        return value

    @field_validator("deadline")
    @classmethod
    def deadline_after_issue(cls, value: datetime, info: object) -> datetime:
        data = getattr(info, "data", {})
        issued_at = data.get("issued_at")
        if isinstance(issued_at, datetime) and value < issued_at:
            raise ValueError("deadline must not precede issued_at")
        return value

    def identity(self) -> tuple[str, str, str]:
        return self.command_id, self.idempotency_key, self.correlation_id


class SharedService:
    def __init__(self, authority: DomainAuthority, authenticator: LocalCredentialAuthenticator | None = None) -> None:
        self.authority = authority
        self.authenticator = authenticator

    def authenticate(self, credential: str | None) -> None:
        if self.authenticator is None:
            raise PermissionError("trusted local credential verifier is not configured")
        try:
            context = self.authenticator.authenticate(credential)
        except LocalCredentialUnavailable as exc:
            raise PermissionError(str(exc)) from exc
        if context != self.authority.context:
            raise PermissionError("credential context does not match authority context")

    def _envelope(self, request: SurfaceCommand) -> CommandEnvelope:
        command_id, idem, correlation = request.identity()
        return CommandEnvelope(command_id=command_id, command_type=request.command_type, idempotency_key=idem,
            correlation_id=correlation, causation_id=request.causation_id,
            tenant_id=self.authority.context.tenant_id, authority_id=self.authority.context.authority_id,
            authority_incarnation=self.authority.context.authority_incarnation, principal_ref=self.authority.context.principal_ref,
            grant_ref=self.authority.context.grant_ref, target_kind=request.target_kind, target_id=request.target_id,
            expected_revision=request.expected_revision, issued_at=request.issued_at, deadline=request.deadline, payload=request.payload)

    @staticmethod
    def _text(payload: dict[str, PayloadValue], key: str) -> str | None:
        value = payload.get(key)
        return value if isinstance(value, str) else None

    @classmethod
    def _refs(cls, payload: dict[str, PayloadValue], key: str) -> tuple[str, ...]:
        value = cls._text(payload, key)
        return tuple(item for item in value.split(",") if item) if value else ()

    @staticmethod
    def _required(payload: dict[str, PayloadValue], key: str) -> str:
        value = payload.get(key)
        if not isinstance(value, str) or not value:
            raise ValueError(f"payload.{key} is required")
        return value

    def command(self, request: SurfaceCommand, credential: str | None = None) -> dict[str, object]:
        self.authenticate(credential)
        envelope = self._envelope(request)
        payload = request.payload
        if request.command_type == "work_item.create":
            result = self.authority.create_work_item(envelope, self._text(payload, "scope_id") or "local-scope", self._text(payload, "agent_slot_id") or "local-slot", self._text(payload, "source_baseline") or "baseline")
            return result.model_dump(mode="json")
        if request.command_type == "work_item.transition":
            state = self._required(payload, "to_state")
            transition = TransitionRequest(to_state=WorkItemState(state), evidence_refs=self._refs(payload, "evidence_refs"), review_ref=self._text(payload, "review_ref"), effect_refs=self._refs(payload, "effect_refs"), readback_refs=self._refs(payload, "readback_refs"))
            return self.authority.transition_work_item(envelope, transition).model_dump(mode="json")
        if request.command_type == "evidence.record":
            evidence = EvidenceRecord.model_validate(payload)
            return self.authority.record_evidence(envelope, evidence).model_dump(mode="json")
        if request.command_type == "review.record":
            return self.authority.record_review(envelope, self._required(payload, "review_id"), request.target_id, self._required(payload, "verdict"), self._required(payload, "evidence_ref"), self._required(payload, "baseline_ref")).model_dump(mode="json")
        if request.command_type == "work_item.read":
            result = self.authority.get_work_item(request.target_id)
            if result is None:
                raise KeyError(request.target_id)
            return dict(result)
        raise ValueError(f"unsupported surface command: {request.command_type}")


def create_app(service: SharedService) -> FastAPI:
    app = FastAPI(title="Agent Collaboration Runtime P1", version="1")

    def credential(value: str | None) -> str:
        if service.authenticator is not None and not value:
            raise HTTPException(status_code=401, detail="trusted local credential is required")
        return value or ""

    @app.post("/v1/commands")
    def submit(request: SurfaceCommand, x_acs_credential: str | None = Header(default=None)) -> dict[str, object]:
        try:
            return service.command(request, credential(x_acs_credential))
        except PermissionError as exc:
            raise HTTPException(status_code=401, detail=str(exc)) from exc
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="work item not found") from exc
        except (RuntimeErrorBase, ValueError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.get("/v1/work-items/{work_item_id}")
    def read(work_item_id: str, x_acs_credential: str | None = Header(default=None)) -> dict[str, object]:
        try:
            service.authenticate(credential(x_acs_credential))
        except PermissionError as exc:
            raise HTTPException(status_code=401, detail=str(exc)) from exc
        result = service.authority.get_work_item(work_item_id)
        if result is None:
            raise HTTPException(status_code=404, detail="work item not found")
        return {key: value for key, value in result.items()}

    return app


def mcp_dispatch(service: SharedService, message: dict[str, object], credential: str | None = None) -> dict[str, object]:
    request_id, method = message.get("id"), message.get("method")
    try:
        if method == "initialize":
            result = {"protocolVersion": "2025-06-18", "serverInfo": {"name": "agent-collaboration-runtime", "version": "0.1.0"}}
        elif method == "tools/list":
            result = {"tools": [{"name": "run", "description": "Submit a durable runtime command", "inputSchema": SurfaceCommand.model_json_schema()}]}
        elif method == "tools/call":
            params = message.get("params")
            if not isinstance(params, dict) or not isinstance(params.get("arguments"), dict):
                raise ValueError("tools/call arguments must be an object")
            output = service.command(SurfaceCommand.model_validate(params["arguments"]), credential)
            result = {"content": [{"type": "text", "text": json.dumps(output, sort_keys=True)}]}
        else:
            raise ValueError(f"unsupported MCP method: {method}")
        return {"jsonrpc": "2.0", "id": request_id, "result": result}
    except (PermissionError, RuntimeErrorBase, ValueError, KeyError) as exc:
        return {"jsonrpc": "2.0", "id": request_id, "error": {"code": -32000, "message": str(exc)}}


cli = typer.Typer(add_completion=False)


def run_cli(service: SharedService, command_json: str, credential: str | None = None) -> str:
    message = {"jsonrpc": "2.0", "id": str(uuid.uuid4()), "method": "tools/call", "params": {"arguments": json.loads(command_json)}}
    return json.dumps(mcp_dispatch(service, message, credential), sort_keys=True)
