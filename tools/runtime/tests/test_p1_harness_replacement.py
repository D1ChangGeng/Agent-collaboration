from __future__ import annotations

import json
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from runtime.recovery_models import (
    DispatchIdentity,
    NativeResponseObservation,
    StateConflict,
    response_receipt_id,
)
from tools.runtime import p1_profile_probe as probe
from tools.runtime.p1_harness_replacement import (
    AcknowledgedFixtureDriver,
    HarnessReplacementProbeError,
    NoModelTerminalDriver,
    read_layer,
)


def test_dispatch_fixture_acknowledges_without_premature_response():
    invocation = SimpleNamespace(
        invocation_id="invocation", dispatch_id="dispatch",
        runtime_dispatched_receipt_id="dispatch-receipt", operation_id="operation",
    )
    driver = AcknowledgedFixtureDriver()
    assert driver.prepare(invocation) is invocation
    observed = driver.invoke(invocation)
    assert observed.native_ack_ref == "fixture-ack"
    assert observed.response_ref is None
    assert driver.calls == ["operation"]


def test_harness_fixture_cannot_invoke_model_and_collects_once():
    identity = DispatchIdentity(
        "tenant", "message", "operation", "invocation", "attempt", "dispatch",
        "endpoint", 1, "machine", "node", "boot", 0, "a" * 64,
    )
    binding = {
        "node_id": "node", "node_boot_id": "boot", "runtime_id": "runtime",
        "attempt_id": "attempt", "agent_slot_id": "slot", "revision": 1,
    }
    driver = NoModelTerminalDriver(
        identity, "command", "driver:binding", binding, "session", "turn",
    )
    with pytest.raises(HarnessReplacementProbeError, match="cannot invoke"):
        driver.invoke(object())
    terminal = driver.collect_result(object(), "operation")
    assert terminal["native_session_id"] == "session"
    assert terminal["attempt_id"] == "attempt"
    assert driver.calls == ["operation"]
    with pytest.raises(HarnessReplacementProbeError, match="more than once"):
        driver.collect_result(object(), "operation")


def test_harness_fixture_adapter_does_not_enable_formal_gate_without_native_evidence():
    scenario = "P1-HARNESS-REPLACEMENT"
    assert scenario in probe.ScenarioCatalog.LINEAGE_BOUND
    available = probe.availability({}, "a" * 40)[scenario]
    assert not available["available"]
    assert "actual native Harness replacement evidence is NOT_RUN" == available["reason"]


def test_same_invocation_cannot_claim_two_node_terminal_observations(tmp_path):
    identity = DispatchIdentity(
        "tenant", "message", "operation", "invocation", "attempt", "dispatch",
        "endpoint", 1, "machine", "node", "boot", 0, "a" * 64,
    )
    outbox = probe.NodeJournal(
        tmp_path / "node.sqlite", machine_id="machine", node_id="node",
        boot_incarnation="boot",
    ).response_outbox()

    def terminal(projection: str):
        return NativeResponseObservation(
            projection, response_receipt_id(identity, projection), identity,
            "native:" + projection, "completed", "artifact:" + projection,
            "b" * 64, "c" * 64, datetime.now(UTC),
        )

    assert outbox.record(terminal("old"))
    with pytest.raises(StateConflict):
        outbox.record(terminal("new"))


def test_harness_proof_readback_rejects_changed_bytes(tmp_path):
    proof = {
        "message_id": "message", "delivery_operation_id": "operation",
        "attempt_id": "attempt", "dispatch_id": "dispatch",
        "machine_id": "machine", "node_id": "node",
        "source_commit": "a" * 40, "source_tree": "b" * 40,
        "old_result_disposition": "fenced_late",
        "new_result_disposition": "current", "head_revision": 2,
        "response_received_count": 1, "accepted_revision_count": 0,
        "no_model_calls": True,
    }
    path = tmp_path / "P1-HARNESS-REPLACEMENT-proof.json"
    encoded = json.dumps(proof, sort_keys=True, separators=(",", ":")).encode()
    path.write_bytes(encoded)
    ledger = SimpleNamespace(root=tmp_path)
    row = {"source_commit": "a" * 40, "source_tree": "b" * 40}
    lineage = {
        "message_id": "message", "operation_id": "operation",
        "attempt_id": "attempt", "dispatch_id": "dispatch",
        "harness_replacement_proof": proof,
    }
    profile = {"machine_id": "machine", "node_id": "node"}
    assert read_layer(profile, "command_output", ledger, row, lineage)[
        "harness_proof_readback"
    ]
    path.write_bytes(encoded + b" ")
    with pytest.raises(HarnessReplacementProbeError, match="proof differs"):
        read_layer(profile, "command_output", ledger, row, lineage)
