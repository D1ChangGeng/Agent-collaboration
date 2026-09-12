"""Shared real JSONL/HTTP fixture checks, not production Node authorization."""
import json
import os
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from runtime.codex_driver import AuthorizedOperation, DriverJournal, DriverRejected
from runtime.delivery import DeliveryRejected
from runtime.delivery_models import DeliveryEnvelope, DeliveryPacket
from runtime.delivery_node import InvocationPreCallRejected, LocalNodeEndpoint
from runtime.native_delivery import NativeDeliveryAdapter
from runtime.node import NodeJournal


def check_adapter(native, tmp_path, monkeypatch, scenario, operation):
    driver = native.driver
    driver.spawn(operation("native-adapter-spawn"))
    journal = NodeJournal(tmp_path / "delivery-node.sqlite", node_id=driver.identity.node_id,
                          boot_incarnation=driver.identity.node_boot_id)
    envelope = DeliveryEnvelope(
        tenant_id="fixture-tenant", authority_id="fixture-authority", authority_incarnation="fixture-incarnation",
        principal_ref="fixture-sender", grant_ref="fixture-send-grant", message_id="message-delivery",
        command_id="command-delivery", operation_id="operation-delivery", endpoint_id="fixture-endpoint",
        binding_revision=1, machine_id=journal.machine_id, node_id=journal.node_id,
        boot_incarnation=journal.boot_incarnation, accepted_state_digest="a" * 64,
        packet=DeliveryPacket(work_item_id="work", target_scope_id="fixture-scope",
                              target_agent_slot_id=driver.identity.agent_slot_id, accepted_revision=0,
                              goal="Synthetic adapter fixture", accepted_state_summary="fixture context",
                              request="synthetic fixture text; no real model is called", source_baseline="fixture-source",
                              expected_response="exact native ACK", activation="invoke",
                              deadline=datetime.now(UTC) + timedelta(seconds=30)),
    )

    def authorize_invocation(invocation, binding):
        assert binding == driver.identity
        return AuthorizedOperation(invocation.invocation_id, invocation.command_id, invocation.message_id,
                                   "grant-test", invocation.envelope.packet.deadline)

    adapter = NativeDeliveryAdapter(driver, authorize_invocation=authorize_invocation)
    endpoint = LocalNodeEndpoint(journal, "fixture-scope", driver.identity.agent_slot_id, adapter)
    invocation = endpoint.invocation(envelope, "fixture-attempt")
    markers = []

    def mutations():
        if driver.harness == "codex":
            return native.state["turn_calls"]
        return sum(path.endswith("/prompt_async") for _, path, _ in native.peer.requests)

    def mark(value, evidence):
        assert value == invocation and evidence["dispatch_id"] == invocation.dispatch_id
        assert mutations() == 0
        markers.append(evidence)
        if scenario == "marker_failure":
            raise RuntimeError("synthetic Domain marker failure")
        if scenario == "marker_rejected":
            raise DeliveryRejected("synthetic_domain_denial", "blocked")

    if scenario.startswith("mutate_"):
        original_fd = driver._claim_fd
        saved_fd = replacement_fd = None
        competitor = competitor_token = None
        released_owner = False
        try:
            with monkeypatch.context() as mutation:
                if scenario == "mutate_binding_id":
                    mutation.setattr(driver, "binding_id", "different-binding")
                elif scenario == "mutate_journal":
                    mutation.setattr(driver, "journal", DriverJournal(tmp_path / "different-journal.sqlite"))
                elif scenario == "mutate_journal_path":
                    mutation.setattr(driver.journal, "path", str(tmp_path / "different-journal-path.sqlite"))
                elif scenario == "mutate_binding_identity":
                    mutation.setattr(driver, "identity", replace(driver.identity, revision=driver.identity.revision + 1))
                elif scenario == "mutate_claim_none":
                    mutation.setattr(driver, "_claim_fd", None)
                elif scenario in {"mutate_claim_same_path_reopen", "mutate_claim_released_owner", "mutate_claim_unlocked_owner"}:
                    claim = adapter._claim_token
                    old_identity = os.fstat(original_fd).st_dev, os.fstat(original_fd).st_ino
                    if scenario == "mutate_claim_unlocked_owner":
                        if os.name != "posix":
                            pytest.skip("Windows share reservation has no byte-unlock operation")
                        import fcntl
                        fcntl.flock(claim._owner_fd, fcntl.LOCK_UN)
                    else:
                        if scenario == "mutate_claim_released_owner":
                            driver.journal.release_claim(claim)
                            released_owner = True
                        else:
                            saved_fd = os.dup(original_fd)
                            os.close(original_fd)
                        reopened = os.open(claim.path, os.O_RDONLY)
                        if reopened != original_fd:
                            os.dup2(reopened, original_fd)
                            os.close(reopened)
                        assert (os.fstat(original_fd).st_dev, os.fstat(original_fd).st_ino) == old_identity
                    competitor = DriverJournal(driver.journal.path)
                    if scenario == "mutate_claim_same_path_reopen":
                        with pytest.raises(DriverRejected):
                            competitor.claim(driver.binding_id)
                    else:
                        competitor_fd = competitor.claim(driver.binding_id)
                        competitor_token = competitor.claim_token(driver.binding_id, competitor_fd)
                else:
                    replacement_fd = os.open(tmp_path / "different-claim.lock", os.O_CREAT | os.O_RDWR, 0o600)
                    if scenario == "mutate_claim_identity":
                        saved_fd = os.dup(original_fd)
                        os.dup2(replacement_fd, original_fd)
                    else:
                        mutation.setattr(driver, "_claim_fd", replacement_fd)
                with pytest.raises(InvocationPreCallRejected):
                    adapter.prepare(invocation)
                with pytest.raises(InvocationPreCallRejected):
                    adapter.invoke(invocation, on_dispatch=lambda: markers.append(True))
                assert mutations() == 0 and markers == []
        finally:
            if competitor_token is not None:
                competitor.release_claim(competitor_token)
            if saved_fd is not None:
                os.dup2(saved_fd, original_fd)
                os.close(saved_fd)
            if replacement_fd is not None:
                os.close(replacement_fd)
            if released_owner:
                os.close(original_fd)
                driver._claim_fd = None
        return

    if scenario == "idle_rejected":
        if driver.harness == "codex":
            native.state["turns"] = [{"id": "busy-turn", "status": "inProgress", "items": []}]
        else:
            native.peer.busy = True
    if scenario == "ack_loss":
        if driver.harness == "codex":
            native.state["drop_invoke_ack"] = True
        else:
            native.peer.drop_prompt_ack = True
    if scenario == "authorization_rejected":
        original = driver.check_current

        def reject_at_final_check(op, binding):
            original(op, binding)
            with driver.journal._connect() as connection:
                events = connection.execute("SELECT body FROM driver_events WHERE operation_id=? "
                                            "AND kind IN ('rpc_intent','http_intent')", (op.operation_id,)).fetchall()
            if any(json.loads(row[0]).get("method") == "turn/start"
                   or json.loads(row[0]).get("path", "").endswith("/prompt_async") for row in events):
                raise DriverRejected("fixture native authority revoked before write")

        monkeypatch.setattr(driver, "check_current", reject_at_final_check)

    if scenario in {"idle_rejected", "authorization_rejected", "marker_rejected"}:
        with pytest.raises(InvocationPreCallRejected):
            endpoint.deliver(envelope, lambda: envelope, invocation, mark, lambda _: False)
        assert len(markers) == (1 if scenario == "marker_rejected" else 0) and mutations() == 0
        assert all(item.layer != "runtime_dispatched" for item in journal.receipts(envelope.operation_id))
    else:
        result = endpoint.deliver(envelope, lambda: envelope, invocation, mark)
        assert len(markers) == 1
        assert result["status"] == ("delivered" if scenario == "success" else "uncertain")
        assert mutations() == (0 if scenario == "marker_failure" else 1)
        layers = [item.layer for item in journal.receipts(envelope.operation_id)]
        assert ("runtime_acknowledged" in layers) == (scenario == "success")
        assert "response_received" not in layers  # ACK is not a model response.
        if scenario in {"success", "ack_loss"}:
            endpoint.deliver(envelope, lambda: envelope, invocation, mark)
            assert mutations() == 1 and len(markers) == 1
