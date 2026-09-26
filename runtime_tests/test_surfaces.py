from __future__ import annotations

import json
import os
import uuid

import pytest
from fastapi.testclient import TestClient

from runtime.domain import DomainAuthority
from runtime.surfaces import SharedService, SurfaceCommand, create_app, mcp_dispatch, run_cli

DSN = os.getenv("ACS_P1_DSN", "")


@pytest.mark.skipif(not DSN, reason="NOT_RUN: ACS_P1_DSN is not set")
def test_local_surface_boundaries_share_authority_and_retry_identity() -> None:
    authority = DomainAuthority(DSN)
    authority.initialize()
    service = SharedService(authority)
    client = TestClient(create_app(service))
    work_item_id = f"surface-{uuid.uuid4()}"
    payload = {"idempotency_key": f"surface-idem-{work_item_id}", "source_baseline": "surface-baseline"}

    unauthenticated = client.post("/v1/commands", json={"command_type": "work_item.create", "target_id": work_item_id, "expected_revision": 0, "payload": payload})
    assert unauthenticated.status_code == 401
    http_response = client.post("/v1/commands", headers={"X-ACS-Principal": authority.context.principal_ref, "X-ACS-Grant": authority.context.grant_ref}, json={"command_type": "work_item.create", "target_id": work_item_id, "expected_revision": 0, "payload": payload})
    assert http_response.status_code == 200
    first = http_response.json()

    cli_response = run_cli(service, SurfaceCommand(command_type="work_item.create", target_id=work_item_id, expected_revision=0, payload=payload).model_dump_json())
    cli_payload = json.loads(cli_response)
    cli_text = cli_payload["result"]["content"][0]["text"]
    assert json.loads(cli_text)["duplicate"] is True

    mcp_response = mcp_dispatch(service, {"jsonrpc": "2.0", "id": "mcp-1", "method": "tools/call", "params": {"arguments": {"command_type": "work_item.create", "target_id": work_item_id, "expected_revision": 0, "payload": payload}}})
    assert mcp_response["result"]["content"]
    mcp_text = mcp_response["result"]["content"][0]["text"]
    assert json.loads(mcp_text)["operation_id"] == first["operation_id"]
