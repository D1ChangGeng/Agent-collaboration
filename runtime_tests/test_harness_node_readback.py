"""Trusted local Node response readback stays bound to its configured endpoint."""
from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

import pytest

from runtime.delivery_node import LocalNodeEndpoint
from runtime.node import NodeJournal
from runtime.recovery_models import (
    BoundaryRejected,
    DispatchIdentity,
    NativeResponseObservation,
    response_receipt_id,
)
from runtime.surface_config import trusted_local_node_response_reader


def test_configured_node_reader_rechecks_endpoint_and_sqlite_record(tmp_path):
    journal = NodeJournal(tmp_path / "node.sqlite", machine_id="machine", node_id="node",
                          boot_incarnation="boot")
    endpoint = LocalNodeEndpoint(journal, "scope", "slot")
    identity = DispatchIdentity(
        "tenant", "message", "operation", "invocation", "attempt", "dispatch",
        "endpoint", 1, "machine", "node", "boot", 0, "a" * 64,
    )
    observation = NativeResponseObservation(
        "projection", response_receipt_id(identity, "projection"), identity,
        "native-response", "completed", "artifact:response", "b" * 64,
        "c" * 64, datetime.now(UTC),
    )
    outbox = journal.response_outbox()
    assert outbox.record(observation)
    reader = trusted_local_node_response_reader({"endpoint": endpoint})
    assert reader(identity) == observation
    with pytest.raises(BoundaryRejected, match="identity changed"):
        reader(replace(identity, machine_id="other-machine"))
    with pytest.raises(BoundaryRejected, match="endpoint is unavailable"):
        trusted_local_node_response_reader({"elsewhere": endpoint})(identity)
