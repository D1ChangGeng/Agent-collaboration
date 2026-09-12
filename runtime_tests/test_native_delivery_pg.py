"""Real Domain/PG marker with native JSONL/HTTP peers and receiver auth fixtures."""
import importlib
from datetime import UTC, datetime, timedelta

import pytest

from runtime.codex_driver import AuthorizedOperation
from runtime.delivery_models import EndpointBindingRequest
from runtime.delivery_node import LocalNodeEndpoint
from runtime.native_delivery import NativeDeliveryAdapter
from runtime.node import NodeJournal
from runtime_tests.test_delivery import command, query, send


@pytest.fixture
def delivery_setup(tmp_path):
    from runtime_tests.test_delivery import setup
    root = tmp_path / "domain"
    root.mkdir(mode=0o700)
    yield from setup.__wrapped__(root)


@pytest.fixture(params=["codex", "opencode"])
def native_setup(request, tmp_path, monkeypatch):
    module = importlib.import_module("runtime_tests.test_" + request.param + "_driver")
    root = tmp_path / "native"
    root.mkdir(mode=0o700)
    selected = module.profile.__wrapped__(root)
    arguments = (root, selected, monkeypatch) if request.param == "codex" else (root, selected)
    fixture = module.native.__wrapped__(*arguments)
    native = next(fixture)
    try:
        native.driver.spawn(module.operation("native-pg-fixture-spawn"))
        yield native
    finally:
        fixture.close()


@pytest.mark.parametrize("scenario", ["success", "pre_marker_revoke", "commit_unknown"])
def test_native_boundary_uses_real_committed_domain_marker(delivery_setup, native_setup, tmp_path, monkeypatch, scenario):
    f, native = delivery_setup, native_setup
    driver = native.driver
    query(f, "INSERT INTO agent_slots(agent_slot_id,tenant_id,scope_id,status) VALUES (%s,%s,'local-scope','active')",
          (driver.identity.agent_slot_id, f.authority.tenant_id))
    journal = NodeJournal(tmp_path / "native-node.sqlite", node_id=driver.identity.node_id,
                          boot_incarnation=driver.identity.node_boot_id)

    def authorize_receiver(invocation, binding):
        # This is explicitly the receiver's test authorizer. The sender's Grant
        # and all Domain dispatch-marker authorization are real PostgreSQL checks.
        assert binding == driver.identity
        return AuthorizedOperation(invocation.invocation_id, invocation.command_id, invocation.message_id,
                                   "receiver-fixture-grant", invocation.envelope.packet.deadline)

    adapter = NativeDeliveryAdapter(driver, authorize_invocation=authorize_receiver)
    endpoint = LocalNodeEndpoint(journal, "local-scope", driver.identity.agent_slot_id, adapter)
    f.service.endpoints["native-endpoint"] = endpoint
    f.service.bind_endpoint(command(f.authority, "message.bind", "native-endpoint"), EndpointBindingRequest(
        scope_id="local-scope", agent_slot_id=driver.identity.agent_slot_id,
        expires_at=datetime.now(UTC) + timedelta(minutes=3)))
    identity, _, _, result = send(f, activation="invoke", target_slot=driver.identity.agent_slot_id,
                                  endpoint_id="native-endpoint")
    original_deliver = endpoint.deliver

    def observed_deliver(*args, **kwargs):
        mark = kwargs["mark_dispatched"]

        def observed_mark(invocation, evidence):
            if scenario == "pre_marker_revoke":
                query(f, "UPDATE grants SET revoked_at=clock_timestamp() WHERE grant_ref=%s",
                      (f.authority.context.grant_ref,))
            mark(invocation, evidence)
            assert query(f, "SELECT receipt_high_water FROM delivery_messages WHERE message_id=%s",
                         (identity["message_id"],)) == [("runtime_dispatched",)]
            if scenario == "commit_unknown":
                raise OSError("fixture lost marker commit response")

        kwargs["mark_dispatched"] = observed_mark
        return original_deliver(*args, **kwargs)

    monkeypatch.setattr(endpoint, "deliver", observed_deliver)
    observed = f.dispatcher.dispatch(identity)
    expected = {"success": "delivered", "pre_marker_revoke": "blocked", "commit_unknown": "uncertain"}[scenario]
    assert observed["status"] == expected
    mutations = native.state["turn_calls"] if driver.harness == "codex" else sum(
        path.endswith("/prompt_async") for _, path, _ in native.peer.requests)
    assert mutations == (1 if scenario == "success" else 0)
    assert query(f, "SELECT count(*) FROM delivery_receipts WHERE layer='runtime_dispatched'") == [(
        0 if scenario == "pre_marker_revoke" else 1,)]
    assert f.dispatcher.dispatch(identity)["status"] == expected
    assert query(f, "SELECT attempts FROM delivery_messages WHERE operation_id=%s", (result.operation_id,)) == [(1,)]
