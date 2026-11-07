"""Bootstrap capabilities must never impersonate a recovery command."""
from types import SimpleNamespace

import pytest

from runtime_deployment.receiver_authority import NativeReceiverAuthority, NativeReceiverRejected


@pytest.mark.parametrize("action", ["resume", "rebind", "prepare", "resume_receiver", "rebind_receiver", "", None, False])
def test_unrecognized_lifecycle_action_cannot_borrow_the_close_identity(action):
    # Reject before consulting any bootstrap identity or contacting an authority.
    receiver = NativeReceiverAuthority()
    with pytest.raises(NativeReceiverRejected, match="lifecycle action is unsupported"):
        receiver._lifecycle_operation(action)


@pytest.mark.parametrize("action", ["spawn", "close"])
def test_existing_bootstrap_action_retains_its_exact_registered_identity(action):
    receiver = NativeReceiverAuthority()
    receiver.settings = {f"{kind}_{field}_id": f"configured-{kind}-{field}"
                         for kind in ("spawn", "close") for field in ("operation", "command", "message")}
    receiver.authority = SimpleNamespace(context=SimpleNamespace(grant_ref="actual-node-grant"))
    receiver.config = SimpleNamespace(access_mode="owner")
    operation = receiver._lifecycle_operation(action)
    assert (operation.operation_id, operation.command_id, operation.message_id, operation.grant_ref, operation.deadline) == (
        f"configured-{action}-operation", f"configured-{action}-command", f"configured-{action}-message", "actual-node-grant", None)
    operation.validate()
