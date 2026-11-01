"""Exact restricted collaboration permissions, using a labeled HTTP fixture."""
import json
import sys
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlsplit

import pytest

from runtime.codex_driver import DriverRejected, file_digest
from runtime.opencode_driver import COLLABORATION_TOOLS
from runtime_tests.test_opencode_driver import native as native_fixture
from runtime_tests.test_opencode_driver import operation
from runtime_tests.test_opencode_driver import profile as profile_fixture

native = native_fixture
profile = profile_fixture


def collaboration_profile(native):
    driver = native.driver
    restricted = replace(driver.profile, collaboration_server="acs")
    config = json.loads(restricted.config_path.read_text())
    config.update(permission=restricted.restricted_permissions(), plugin=[],
        mcp={"acs": {"type": "local", "command": [sys.executable, "approved-entry.py"], "enabled": True}})
    config["agent"][restricted.agent]["permission"] = restricted.restricted_permissions()
    restricted.config_path.write_text(json.dumps(config))
    driver.profile = replace(restricted, config_sha256=file_digest(restricted.config_path))
    driver.observe_events = False
    return driver


def test_exact_acs_permissions_round_trip_without_execution_subscription(native, monkeypatch):
    driver = collaboration_profile(native)
    launch = driver.supervisor.launch
    def start(*args, **kwargs):
        owned = launch(*args, **kwargs)
        handler = native.peer.server.RequestHandlerClass
        answer = handler.answer
        def observed(self, status, value=None):
            if urlsplit(self.path).path == "/agent":
                value = [{**agent, "permission": driver.profile.session_permissions()} for agent in value]
            return answer(self, status, value)
        monkeypatch.setattr(handler, "answer", observed)
        return owned
    monkeypatch.setattr(driver.supervisor, "launch", start)
    assert driver.spawn(operation("shared-spawn"))["receipt_layer"] == "runtime_acknowledged"
    assert set(driver.profile.collaboration_permissions()) == {"acs_" + name for name in COLLABORATION_TOOLS}
    assert driver._event_thread is None
    assert not any(path == "/event" for _, path, _ in native.peer.requests)


def test_missing_positive_native_acs_permissions_fails_before_session_create(native):
    driver = collaboration_profile(native)
    with pytest.raises(DriverRejected, match="not positively observed"):
        driver.spawn(operation("missing-native-permissions"))
    assert not any(method == "POST" and path == "/session" for method, path, _ in native.peer.requests)


@pytest.mark.parametrize("extra", [{"bash": "allow"}, {"read": "allow"}, {"task": "allow"}, {"acs_*": "allow"}, {"other_read_message": "allow"}])
def test_restricted_config_rejects_additional_tools_even_when_hash_is_pinned(native, extra):
    driver = collaboration_profile(native)
    config = json.loads(driver.profile.config_path.read_text())
    config["permission"].update(extra)
    driver.profile.config_path.write_text(json.dumps(config))
    driver.profile = replace(driver.profile, config_sha256=file_digest(driver.profile.config_path))
    with pytest.raises(DriverRejected, match="deny-all"):
        driver.profile.validate()


@pytest.mark.parametrize("entry", [{"type": "remote", "url": "https://example.invalid", "enabled": True},
    {"type": "local", "command": ["relative-python"], "enabled": True}])
def test_shared_collaboration_requires_an_explicit_local_entry(native, entry):
    driver = collaboration_profile(native)
    config = json.loads(driver.profile.config_path.read_text()); config["mcp"]["acs"] = entry
    driver.profile.config_path.write_text(json.dumps(config))
    driver.profile = replace(driver.profile, config_sha256=file_digest(driver.profile.config_path))
    with pytest.raises(DriverRejected, match="one pinned local MCP"):
        driver.profile.validate()


def test_mcp_inventory_http_route_cannot_mutate_a_server(tmp_path):
    from runtime.opencode_http import HttpRejected, LoopbackHttp
    client = LoopbackHttp(12345, "x" * 32, str(tmp_path), lambda: pytest.fail("must reject before network access"))
    with pytest.raises(HttpRejected, match="read-only"):
        client.request("POST", "/mcp", {})


def unbounded_adapter(native):
    from runtime.codex_driver import AuthorizedOperation
    from runtime.delivery_models import DeliveryEnvelope, MessagePacket
    from runtime.delivery_node import invocation_for
    from runtime.native_delivery import NativeDeliveryAdapter
    driver = native.driver
    driver.spawn(operation("no-business-deadline"))
    packet = MessagePacket(project_id="project", sender="collaborator:project:sender",
        recipient="collaborator:project:slot", content="natural request", target_scope_id="scope", target_agent_slot_id="slot")
    value = DeliveryEnvelope(tenant_id="tenant", authority_id="authority", authority_incarnation="incarnation",
        principal_ref="sender", grant_ref="grant", message_id="message", command_id="command", operation_id="operation",
        endpoint_id="endpoint", binding_revision=1, machine_id="machine", node_id="node", boot_incarnation="boot",
        accepted_state_digest="a" * 64, packet=packet)
    invocation = invocation_for(value, "attempt")
    adapter = NativeDeliveryAdapter(driver, authorize_invocation=lambda request, identity: AuthorizedOperation(
        request.invocation_id, request.command_id, request.message_id, request.envelope.grant_ref, None))
    return adapter, invocation


def test_restricted_natural_message_without_deadline_keeps_a_bounded_idle_lease(native):
    adapter, invocation = unbounded_adapter(native)
    readiness = adapter.readiness(invocation)
    assert readiness["activity"] == "idle" and adapter._readiness_fresh(readiness)
    remaining = (datetime.fromisoformat(readiness["expires_at"]) - datetime.now(UTC)).total_seconds()
    assert 0 < remaining <= 2


def test_transport_observation_does_not_replace_local_invocation_lease(native):
    adapter, invocation = unbounded_adapter(native)
    transported = adapter.transport_readiness(invocation)
    remaining = (datetime.fromisoformat(transported["expires_at"]) - datetime.now(UTC)).total_seconds()
    assert 2 < remaining <= 15
    local = adapter.readiness(invocation)
    assert (datetime.fromisoformat(local["expires_at"]) - datetime.now(UTC)).total_seconds() <= 2
    assert not adapter._readiness_fresh(transported)


def test_slow_status_response_consumes_the_local_lease(native, monkeypatch):
    from runtime import native_delivery
    adapter, invocation = unbounded_adapter(native)
    anchor = datetime.now(UTC)
    elapsed = {"seconds": 0}
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return anchor + timedelta(seconds=elapsed["seconds"])
    monkeypatch.setattr(native_delivery, "datetime", Clock)
    monkeypatch.setattr(native_delivery, "time", SimpleNamespace(monotonic=lambda: elapsed["seconds"]))
    def delayed(_operation, *, before_status):
        before_status()
        elapsed["seconds"] = 3
        return {"status": {"type": "idle"}}
    monkeypatch.setattr(native.driver, "inspect_readiness", delayed)
    readiness = adapter.readiness(invocation)
    assert datetime.fromisoformat(readiness["expires_at"]) <= anchor + timedelta(seconds=2)
    assert not adapter._readiness_fresh(readiness)


def test_collaboration_keeps_generated_native_data_out_of_pinned_config(native):
    driver = collaboration_profile(native)
    environment = driver.profile.process_environment("x" * 32)
    assert environment["OPENCODE_CONFIG"] == str(driver.profile.config_path)
    assert "OPENCODE_CONFIG_DIR" not in environment
    assert Path(environment["XDG_CONFIG_HOME"]).is_relative_to(Path(driver.profile.state_root))
    assert environment["OPENCODE_DISABLE_DEFAULT_PLUGINS"] == "1"


def test_observed_opencode_11834_schema_is_pinned_and_contains_readiness_paths():
    schema = Path(__file__).parent / "schema-1.18.34/opencode-openapi.json"
    assert file_digest(schema) == "100c603616f4ab443ea0557b64840a78108028806503522ffc80d587461a9a98"
    paths = json.loads(schema.read_text())["paths"]
    assert {"/global/health", "/config", "/agent", "/mcp", "/session", "/session/status"} <= paths.keys()
