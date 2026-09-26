from __future__ import annotations

import hashlib
import json
import os
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from runtime.auth import LocalCredentialAuthenticator
from runtime.domain import DomainAuthority
from runtime.models import AuthenticatedContext
from runtime.surfaces import SharedService, SurfaceCommand, create_app, mcp_dispatch, run_cli

DSN = os.getenv("ACS_P1_DSN", "")


def _service() -> tuple[SharedService, str]:
    secret = "surface-secret"
    context = AuthenticatedContext("local-tenant", "acs-p1-authority", "local-1", "agent:engineer", "grant:p1", hashlib.sha256(secret.encode()).hexdigest())
    authority = DomainAuthority(DSN, context)
    return SharedService(authority, LocalCredentialAuthenticator(context)), secret


@pytest.mark.skipif(not DSN, reason="NOT_RUN: ACS_P1_DSN is not set")
def test_http_cli_mcp_boundaries_preserve_command_identity() -> None:
    service, secret = _service()
    service.authority.initialize()
    service.authority.bootstrap_local_grant()
    client = TestClient(create_app(service))
    work_item_id = f"surface-{uuid.uuid4()}"
    payload = {"idempotency_key": f"surface-idem-{work_item_id}", "source_baseline": "surface-baseline"}
    issued_at = datetime.now(UTC)
    request = {"command_type": "work_item.create", "target_id": work_item_id, "expected_revision": 0,
               "command_id": f"cmd-{work_item_id}", "idempotency_key": f"idem-{work_item_id}",
               "correlation_id": f"corr-{work_item_id}", "issued_at": issued_at.isoformat(),
               "deadline": (issued_at + timedelta(minutes=5)).isoformat(), "payload": payload}

    assert client.post("/v1/commands", json=request).status_code == 401
    assert client.get(f"/v1/work-items/{work_item_id}", headers={"X-ACS-Credential": "wrong"}).status_code == 401
    response = client.post("/v1/commands", headers={"X-ACS-Credential": secret}, json=request)
    assert response.status_code == 200
    first = response.json()

    cli_result = json.loads(run_cli(service, json.dumps(request), secret))
    assert isinstance(cli_result, dict)
    cli_result_body = cli_result.get("result")
    assert isinstance(cli_result_body, dict)
    cli_content = cli_result_body.get("content")
    assert isinstance(cli_content, list) and cli_content
    assert isinstance(cli_content[0], dict)
    cli_text = cli_content[0]["text"]
    assert json.loads(cli_text)["duplicate"] is True

    mcp_result = mcp_dispatch(service, {"jsonrpc": "2.0", "id": "mcp-1", "method": "tools/call", "params": {"arguments": request}}, secret)
    assert isinstance(mcp_result, dict)
    mcp_body = mcp_result.get("result")
    assert isinstance(mcp_body, dict)
    mcp_content = mcp_body.get("content")
    assert isinstance(mcp_content, list) and mcp_content
    assert isinstance(mcp_content[0], dict)
    mcp_text = mcp_content[0]["text"]
    assert json.loads(mcp_text)["operation_id"] == first["operation_id"]


def test_surface_command_keeps_explicit_timestamps_and_rejects_naive_deadline() -> None:
    now = datetime.now(UTC)
    command = SurfaceCommand(command_type="work_item.create", target_id="w", expected_revision=0,
                             command_id="cmd-w", idempotency_key="idem-w", correlation_id="corr-w",
                             issued_at=now, deadline=now + timedelta(minutes=1))
    assert command.issued_at == now
    with pytest.raises(ValueError):
        SurfaceCommand(command_type="work_item.create", target_id="w", expected_revision=0,
                       command_id="cmd-w", idempotency_key="idem-w", correlation_id="corr-w",
                       issued_at=datetime.now(UTC).replace(tzinfo=None), deadline=datetime.now(UTC) + timedelta(minutes=1))


def test_mcp_protocol_surfaces_are_real_json_rpc_boundaries() -> None:
    service, _ = _service()
    initialized = mcp_dispatch(service, {"jsonrpc": "2.0", "id": 1, "method": "initialize"})
    listed = mcp_dispatch(service, {"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
    init_body = initialized.get("result")
    assert isinstance(init_body, dict)
    assert init_body.get("protocolVersion") == "2025-06-18"
    list_body = listed.get("result")
    assert isinstance(list_body, dict)
    tools = list_body.get("tools")
    assert isinstance(tools, list) and tools and isinstance(tools[0], dict)
    assert tools[0].get("name") == "run"
