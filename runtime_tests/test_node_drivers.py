from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from runtime.drivers import (
    CodexDriver,
    DriverCapabilities,
    DriverInvocation,
    DriverReceipt,
    EndpointDriverAdapter,
)
from runtime.node import JournalOperation, NodeJournal, OperationIdentityConflict
from runtime.provider import (
    CommittedOperation,
    InMemoryOperationReferenceStore,
    TemporalReferenceProvider,
)


class RecordingDriverEndpoint:
    def __init__(self) -> None:
        self.invocations: list[tuple[str, DriverInvocation]] = []

    def invoke(self, harness: str, invocation: DriverInvocation) -> DriverReceipt:
        self.invocations.append((harness, invocation))
        return DriverReceipt(
            operation_id=invocation.operation_id,
            command_id=invocation.command_id,
            message_id=invocation.message_id,
            harness=harness,
            receipt_layer="accepted_by_driver",
            session_ref=f"{harness}-session-1",
            observed_at=datetime.now(UTC),
        )


def operation() -> JournalOperation:
    return JournalOperation(
        operation_id="op-1",
        command_id="cmd-1",
        message_id="msg-1",
        operation_kind="delivery.dispatch",
        payload_sha256="a" * 64,
    )


def test_node_journal_returns_original_operation_after_restart(tmp_path: Path) -> None:
    # Given: a durable journal and one submitted operation.
    journal_path = tmp_path / "node.sqlite3"
    given = NodeJournal(journal_path)
    given.append(operation())

    # When: a restarted Node opens the same local journal.
    restarted = NodeJournal(journal_path)
    actual = restarted.read("op-1")

    # Then: the immutable logical operation identity is recovered unchanged.
    assert actual == operation()


def test_node_journal_rejects_operation_id_reuse_with_different_identity(tmp_path: Path) -> None:
    # Given: an operation identity already durably recorded.
    journal = NodeJournal(tmp_path / "node.sqlite3")
    journal.append(operation())
    conflicting = JournalOperation(
        operation_id="op-1",
        command_id="cmd-2",
        message_id="msg-1",
        operation_kind="delivery.dispatch",
        payload_sha256="a" * 64,
    )

    # When: a retry attempts to change that identity.
    with pytest.raises(OperationIdentityConflict):
        journal.append(conflicting)

    # Then: the original durable operation remains authoritative.
    assert journal.read("op-1") == operation()


@pytest.mark.parametrize(
    "harness",
    ["codex", "opencode"],
)
def test_explicit_endpoint_adapter_preserves_its_receipt(
    harness: str
) -> None:
    # An explicit synthetic endpoint exercises adapter identity, not native conformance.
    endpoint = RecordingDriverEndpoint()
    driver = EndpointDriverAdapter(harness, endpoint)
    invocation = DriverInvocation(
        operation_id="op-1",
        command_id="cmd-1",
        message_id="msg-1",
        agent_slot_id="engineer-runtime-1302",
    )

    # The adapter forwards the call to this test endpoint.
    receipt = driver.invoke(invocation)

    # Then: capability and receipt name only the observed driver layer.
    assert driver.capabilities() == DriverCapabilities(harness=harness, actions=("invoke",))
    assert endpoint.invocations == [(harness, invocation)]
    assert receipt.receipt_layer == "accepted_by_driver"
    assert receipt.operation_id == invocation.operation_id
    assert receipt.session_ref == f"{harness}-session-1"


def test_temporal_reference_provider_records_only_committed_operation_reference() -> None:
    # Given: a committed authority operation and a deterministic test store.
    store = InMemoryOperationReferenceStore()
    provider = TemporalReferenceProvider(store)
    committed = CommittedOperation(
        operation_id="op-1",
        tenant_id="tenant-1",
        command_id="cmd-1",
        committed_at=datetime(2026, 9, 11, tzinfo=UTC),
    )

    # When: the provider receives that already committed operation.
    reference = provider.submit(committed)

    # Then: it records one stable Temporal workflow reference and no domain decision.
    assert reference.workflow_id == "acs-p1/op-1"
    assert reference.operation_id == committed.operation_id
    assert store.references() == (reference,)
    assert provider.submit(committed) == reference


def test_temporal_reference_provider_rejects_uncommitted_operation() -> None:
    # Given: an operation that the authority has not committed.
    provider = TemporalReferenceProvider(InMemoryOperationReferenceStore())
    uncommitted = CommittedOperation(
        operation_id="op-1",
        tenant_id="tenant-1",
        command_id="cmd-1",
        committed_at=None,
    )

    # When: it is offered to the reference provider.
    with pytest.raises(ValueError, match="committed"):
        provider.submit(uncommitted)

    # Then: no workflow reference can be created from an uncommitted command.


def test_public_codex_driver_uses_native_app_server_implementation():
    from runtime.codex_driver import CodexAppServerDriver

    assert CodexDriver is CodexAppServerDriver
