"""Actual CLI, MCP and HTTP exposure of the shared recovery command schema."""
from __future__ import annotations

import asyncio

import httpx

from runtime.surfaces import PAYLOADS
from runtime_tests.test_surfaces import cli, http_process, request, sdk_call
from runtime_tests.test_surfaces import pg as pg  # noqa: PLC0414


def test_recovery_status_uses_same_actual_cli_mcp_and_http_surface(pg):
    authority, configured = pg
    config, environment, secret = configured
    with authority._connect() as connection:
        connection.execute(
            "UPDATE grants SET permissions=permissions || %s::jsonb WHERE grant_ref=%s",
            ('["recovery.read"]', authority.context.grant_ref),
        )
    value = request(
        "recovery.incident.status",
        target="missing-incident",
        target_kind="recovery",
        payload={"incident_id": "missing-incident", "scope_id": "local-scope"},
    )
    process, cli_result = cli(config, environment, value)
    assert process.returncode == 0 and cli_result["ok"] and cli_result["result"] is None
    _initialized, tools, mcp, errors = asyncio.run(sdk_call(config, environment, [value]))
    assert tools.tools[0].name == "run"
    assert not mcp[0].is_error and mcp[0].structured_content["result"] is None
    assert secret not in errors
    with http_process(config, environment) as url:
        response = httpx.post(
            url + "/v1/commands", json=value,
            headers={"X-ACS-Credential": secret}, timeout=10,
        )
        assert response.status_code == 200
        assert response.json()["ok"] and response.json()["result"] is None
    assert {
        "delivery.project_native_response", "delivery.projection.status",
        "delivery.response.consume", "recovery.incident.open",
        "recovery.human.request", "recovery.automatic.reprobe",
        "recovery.manual.receive", "recovery.manual.confirm",
        "recovery.incident.expire", "recovery.incident.status",
    } <= set(PAYLOADS)
