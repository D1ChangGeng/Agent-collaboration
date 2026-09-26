from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import typer
from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from runtime.domain import DomainAuthority
from runtime.errors import RuntimeErrorBase
from runtime.models import CommandEnvelope, PayloadValue, TransitionRequest, WorkItemState


class SurfaceCommand(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    command_type: str = Field(min_length=1)
    target_id: str = Field(min_length=1)
    expected_revision: int = Field(ge=0)
    payload: dict[str, PayloadValue] = Field(default_factory=dict)


class SharedService:
    def __init__(self, authority: DomainAuthority) -> None:
        self.authority = authority

    def command(self, request: SurfaceCommand) -> dict[str, object]:
        now = datetime.now(UTC)
        idempotency = request.payload.get("idempotency_key")
        idempotency_key = idempotency if isinstance(idempotency, str) else f"idem-{request.target_id}"
        def text(name: str) -> str | None:
            value = request.payload.get(name)
            return value if isinstance(value, str) else None
        command = CommandEnvelope(
            command_id=f"cmd-{idempotency_key}",
            command_type=request.command_type,
            idempotency_key=idempotency_key,
            correlation_id=f"corr-{idempotency_key}",
            tenant_id=self.authority.context.tenant_id,
            authority_id=self.authority.context.authority_id,
            authority_incarnation=self.authority.context.authority_incarnation,
            principal_ref=self.authority.context.principal_ref,
            grant_ref=self.authority.context.grant_ref,
            target_kind="work_item",
            target_id=request.target_id,
            expected_revision=request.expected_revision,
            issued_at=now,
            deadline=now + timedelta(minutes=5),
            payload=request.payload,
        )
        if request.command_type == "work_item.create":
            result = self.authority.create_work_item(command, "local-scope", "local-slot", text("source_baseline") or "baseline")
        elif request.command_type == "work_item.transition":
            result = self.authority.transition_work_item(
                command,
                TransitionRequest(
                    to_state=WorkItemState(text("to_state") or "candidate"),
                    evidence_refs=tuple((text("evidence_refs") or "").split(",")) if text("evidence_refs") else (),
                    review_ref=text("review_ref"),
                    effect_refs=tuple((text("effect_refs") or "").split(",")) if text("effect_refs") else (),
                    readback_refs=tuple((text("readback_refs") or "").split(",")) if text("readback_refs") else (),
                ),
            )
        else:
            raise ValueError(f"unsupported surface command: {request.command_type}")
        return result.model_dump(mode="json")


def create_app(service: SharedService) -> FastAPI:
    app = FastAPI(title="Agent Collaboration Runtime P1")

    @app.post("/v1/commands")
    def command(
        request: SurfaceCommand,
        x_acs_principal: str | None = Header(default=None),
        x_acs_grant: str | None = Header(default=None),
    ) -> dict[str, object]:
        if x_acs_principal != service.authority.context.principal_ref or x_acs_grant != service.authority.context.grant_ref:
            raise HTTPException(status_code=401, detail="trusted runtime headers are required")
        try:
            return service.command(request)
        except RuntimeErrorBase as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.get("/v1/work-items/{work_item_id}")
    def get_work_item(work_item_id: str) -> dict[str, object]:
        result = service.authority.get_work_item(work_item_id)
        if result is None:
            raise HTTPException(status_code=404, detail="work item not found")
        return result

    return app


def mcp_dispatch(service: SharedService, message: dict[str, object]) -> dict[str, object]:
    method = message.get("method")
    request_id = message.get("id")
    if method == "initialize":
        result = {"protocolVersion": "2025-06-18", "serverInfo": {"name": "agent-collaboration-runtime", "version": "0.1.0"}}
    elif method == "tools/list":
        result = {"tools": [{"name": "run", "description": "Submit a durable runtime command", "inputSchema": {"type": "object"}}]}
    elif method == "tools/call":
        params = message.get("params")
        if not isinstance(params, dict):
            raise ValueError("tools/call params must be an object")
        arguments = params.get("arguments")
        if not isinstance(arguments, dict):
            raise ValueError("tools/call arguments must be an object")
        result = {"content": [{"type": "text", "text": json.dumps(service.command(SurfaceCommand.model_validate(arguments)), sort_keys=True)}]}
    else:
        raise ValueError(f"unsupported MCP method: {method}")
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


cli = typer.Typer(add_completion=False)


def run_cli(service: SharedService, command_json: str) -> str:
    result = mcp_dispatch(service, {"jsonrpc": "2.0", "id": "cli-1", "method": "tools/call", "params": {"arguments": json.loads(command_json)}})
    return json.dumps(result, sort_keys=True)
