"""Reject cross-layer substitutions before an OpenCode Gate record can form."""

from __future__ import annotations

import copy

import pytest

from tools.runtime.p1_opencode_readback import (
    OpenCodeReadbackRejected,
    validate_opencode_lineage,
)


def complete():
    attempt = "delivery-attempt-a"
    invocation = "delivery-invocation:" + attempt
    dispatch = "delivery-dispatch:" + attempt
    identity = ["message-a", "operation-a", attempt, invocation, dispatch]
    return {
        "run_id": "p1-opencode-run-a",
        "source_commit": "a" * 40,
        "source_tree": "b" * 40,
        "machine_id": "machine-a",
        "node_id": "node-a",
        "command_id": "command-a",
        "message_id": identity[0],
        "operation_id": identity[1],
        "attempt_id": attempt,
        "dispatch_id": dispatch,
        "invocation_id": invocation,
        "native_session_id": "ses_a",
        "native_message_id": "msg_a",
        "native_assistant_ids": ["msg_answer_a"],
        "pg": {
            "identity": identity, "selection_machine_id": "machine-a",
            "selection_node_id": "node-a", "attempt_count": 1,
            "dispatch_marker_count": 1, "event_count": 1, "outbox_count": 1,
            "response_projection_count": 1, "response_receipt_count": 1,
        },
        "node": {
            "identity": identity, "machine_id": "machine-a", "node_id": "node-a",
            "mailbox_count": 1, "invocation_count": 1, "response_outbox_count": 1,
        },
        "temporal": {"workflow_id": "acs-delivery/operation-a", "run_id": "temporal-run-a",
                     "status": "delivered"},
        "driver": {
            "invocation_id": invocation, "session_id": "ses_a", "message_id": "msg_a",
            "assistant_ids": ["msg_answer_a"], "prompt_async_count": 1,
            "terminal_status": "completed", "assistant_text_exact": True,
        },
        "response": {
            "invocation_id": invocation, "disposition": "applied",
            "artifact_readback": True, "digest_match": True,
            "response_digest": "c" * 64, "projection_id": "projection:fixture",
        },
        "os": {
            "verified": True, "remaining_pids": [], "root_exited": True,
            "wrapper_exited": True, "unit": "acs-p1-opencode-run-a.service",
        },
    }


def test_complete_lineage_admitted():
    assert validate_opencode_lineage(complete())["driver"]["prompt_async_count"] == 1


@pytest.mark.parametrize(
    "layer,key,replacement",
    [
        ("pg", "selection_machine_id", "other-machine"),
        ("pg", "response_receipt_count", 0),
        ("node", "response_outbox_count", 0),
        ("temporal", "run_id", ""),
        ("driver", "prompt_async_count", 2),
        ("driver", "message_id", "other-message"),
        ("response", "artifact_readback", False),
        ("os", "remaining_pids", [123]),
    ],
)
def test_substituted_layer_rejected(layer, key, replacement):
    value = copy.deepcopy(complete())
    value[layer][key] = replacement
    with pytest.raises(OpenCodeReadbackRejected):
        validate_opencode_lineage(value)
