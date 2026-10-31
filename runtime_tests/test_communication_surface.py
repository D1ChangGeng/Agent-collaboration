"""Current technical commands and retired business entry points, on real transports."""
from __future__ import annotations

import asyncio
import json

import httpx
import psycopg

from runtime.delivery import DeliveryDispatcher, DeliveryRejected, DeliveryService
from runtime.domain import DomainAuthority
from runtime.surface_config import configured_service
from runtime.surfaces import PAYLOADS, SurfaceCommand
from runtime_tests.test_communication import comm as comm_fixture
from runtime_tests.test_communication import send
from runtime_tests.test_communication_archive import seed_legacy
from runtime_tests.test_project_service import project as project_fixture
from runtime_tests.test_surfaces import cli, http_process, profile, request, sdk_call

comm = comm_fixture
project = project_fixture
RETIRED = (
    "work_item.create", "work_item.transition", "work_item.read", "evidence.record", "execution.record",
    "review.assign", "review.record", "attempt.register", "lease.acquire", "lease.renew", "lease.release",
    "lease.revoke", "effect.register", "effect.reconcile", "harness_session.attach", "harness_session.read",
    "harness_session.result", "recovery.incident.open", "recovery.incident.status", "recovery.human.request",
    "recovery.automatic.reprobe", "recovery.manual.receive", "recovery.manual.confirm", "recovery.incident.expire",
    "delivery.project_native_response", "delivery.projection.status", "delivery.response.consume", "message.send",
)


def test_current_cli_mcp_http_reject_retired_commands_without_a_database(tmp_path):
    config, environment, secret = profile(tmp_path)
    # Valid current target_kind ensures unsupported command rejection, rather
    # than merely testing the narrower enum's validation.
    values = [request(name, target_kind="message") for name in RETIRED]
    for value in values[:3]:
        process, result = cli(config, environment, value)
        assert process.returncode == 1 and result["error"]["code"] == "INPUT_INVALID"
        assert secret.encode() not in process.stdout + process.stderr
    _initialized, tools, results, errors = asyncio.run(sdk_call(config, environment, values))
    assert tools.tools[0].input_schema["$defs"]["SurfaceCommand"]["properties"]["target_kind"]["default"] == "message"
    assert all(result.is_error and result.structured_content["error"]["code"] == "INPUT_INVALID" for result in results)
    assert secret not in errors
    with http_process(config, environment) as url:
        schema = httpx.get(url + "/v1/schema", timeout=10).json()
        assert not set(RETIRED).intersection(schema["payloads"])
        assert set(schema["payloads"]) == set(PAYLOADS)
        assert set(schema["command"]["properties"]["command_type"]["enum"]) == set(PAYLOADS)
        assert not {"work_item", "attempt", "lease", "effect", "recovery", "projection"}.intersection(
            schema["command"]["properties"]["target_kind"]["enum"])
        for value in values:
            reply = httpx.post(url + "/v1/commands", json=value, headers={"X-ACS-Credential": secret}, timeout=10)
            assert reply.status_code == 422 and reply.json()["error"]["code"] == "INPUT_INVALID"
        unauthorized = httpx.post(url + "/v1/commands", json=values[0], timeout=10)
        assert unauthorized.status_code == 401


def test_old_effect_configuration_cannot_construct_a_task_gateway(tmp_path, monkeypatch):
    retired_root = tmp_path / "retired-effects"
    config, environment, _secret = profile(tmp_path, extra={"effects": {
        "root": str(retired_root), "scope_id": "local-scope", "resource_paths": {"file": "unused.txt"}}})
    for key, value in environment.items():
        monkeypatch.setenv(key, value)
    with configured_service(config) as (service, _settings):
        assert not hasattr(service, "recovery")
        assert not hasattr(service.authority, "_effect_registration_gateway")
        assert not retired_root.exists()


def operator_request(name, target, payload):
    return SurfaceCommand.model_validate_json(json.dumps(request(name, target=target, target_kind="message", payload=payload)))


def enable_operator(authority):
    with authority._connect() as connection:
        connection.execute("UPDATE grants SET permissions=permissions || '[\"delivery.scan\",\"delivery.dispatch\"]'::jsonb "
                           "WHERE grant_ref=%s", (authority.context.grant_ref,))


def test_operator_dispatches_current_message_without_task_audit_fields(comm):
    enable_operator(comm.authority)
    sent = send(comm)["data"]
    service = comm.clients["a"].service.service
    credential = comm.clients["a"].credential_provider()
    scanned = service.command(operator_request("delivery.scan", "pending", {"scope_id": "local-scope"}), credential)
    assert [item["message_id"] for item in scanned["pending"]] == [sent["message_id"]]
    dispatched = service.command(operator_request("delivery.dispatch", sent["message_id"], {"operation_id": sent["operation_id"]}), credential)
    assert dispatched["delivery"]["state"] == "delivered" and not dispatched["operator_pending"]
    assert len(comm.drivers["b"].calls) == 1
    with psycopg.connect(comm.dsn) as connection:
        assert connection.execute("SELECT related_work_item_id FROM domain_events WHERE to_state='delivery.dispatch.authorized'").fetchone() == (None,)
        assert connection.execute("SELECT count(*) FROM work_items").fetchone()[0] == 0


def test_operator_scan_and_dispatch_keep_legacy_tasks_read_only(project):
    identity, _packet = seed_legacy(project)
    enable_operator(project.authority)
    operations = project.projects.service.delivery_operations
    from runtime_tests.test_delivery import command

    scan = operations.scan(command(project.authority, "delivery.scan", "pending"), scope_id="local-scope", limit=16)
    assert scan["pending"] == []
    with project.authority._connect() as connection:
        before = connection.execute("SELECT packet_json,command_json,state,attempts FROM delivery_messages WHERE message_id=%s",
                                    (identity["message_id"],)).fetchone()
    import pytest

    with pytest.raises(DeliveryRejected, match="historical_delivery_read_only"):
        operations.dispatch(command(project.authority, "delivery.dispatch", identity["message_id"]), operation_id=identity["operation_id"])
    with project.authority._connect() as connection:
        assert connection.execute("SELECT packet_json,command_json,state,attempts FROM delivery_messages WHERE message_id=%s",
                                  (identity["message_id"],)).fetchone() == before
        assert connection.execute("SELECT count(*) FROM delivery_attempts").fetchone()[0] == 0
    assert project.driver.calls == []


def test_current_domain_and_delivery_library_cannot_create_legacy_task_packets(project):
    identity, packet = seed_legacy(project)
    from runtime_tests.test_delivery import command

    current = DomainAuthority(project.dsn, context=project.authority.context)
    current_delivery = DeliveryService(current, project.service.endpoints)
    import pytest

    with current._connect() as connection:
        before = connection.execute("SELECT count(*) FROM delivery_messages").fetchone()[0]
    with pytest.raises(DeliveryRejected, match="historical_delivery_read_only"):
        current_delivery.send_message(command(current, "message.send", "new-legacy-packet"), packet,
                                      endpoint_id="endpoint", binding_revision=1)
    with pytest.raises(DeliveryRejected, match="historical_delivery_read_only"):
        current.send_message(command(current, "message.send", "another-legacy-packet"), packet,
                             endpoint_id="endpoint", binding_revision=1)
    with current._connect() as connection:
        assert connection.execute("SELECT count(*) FROM delivery_messages").fetchone()[0] == before
        assert connection.execute("SELECT packet_json FROM delivery_messages WHERE message_id=%s",
                                  (identity["message_id"],)).fetchone()[0] == packet.model_dump(mode="json")
    observed = DeliveryDispatcher(current_delivery).dispatch(identity)
    assert observed["status"] == "blocked" and observed["attempts"] == 0
    assert project.driver.calls == []
