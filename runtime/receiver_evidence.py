"""Project-authorized receiver projections; no lifecycle or input side effects."""
from __future__ import annotations

import json

from runtime.receiver_contract import (
    CapabilityScope,
    ReceiverBinding,
    ReceiverSnapshot,
    unknown_capabilities,
    unknown_observations,
)


def unknown_receiver(binding: ReceiverBinding, *, reason: str) -> ReceiverSnapshot:
    return ReceiverSnapshot(receiver_id=binding.receiver_id, address=binding.actor_address,
        binding_epoch=binding.binding_epoch, revision=binding.binding_epoch,
        native_session_ref=None,
        capability_scope=CapabilityScope(adapter_id="unverified", adapter_version="unknown",
            harness_kind="unknown", harness_version=None, execution_host_ref=binding.execution_host_ref,
            binary_digest=None, config_digest=None, connection_epoch=binding.binding_epoch,
            provider_generation=binding.provider_generation),
        capabilities=unknown_capabilities(),
        observations=unknown_observations(binding.binding_epoch, binding.provider_generation, reason),
        allowed_actions=())


def project_receiver(provider, binding: ReceiverBinding, now, *, expected_node=None) -> ReceiverSnapshot:
    """Use only an already-authorized provider. Readback failure stays unknown.

    Callers must recheck their live project authorization and endpoint revision
    after this potentially slow read, before returning it to the caller.
    """
    read = getattr(provider, "receiver_snapshot", None)
    if not callable(read):
        return unknown_receiver(binding, reason="receiver_contract_unavailable")
    try:
        if expected_node is not None:
            descriptor = provider.descriptor()
            if any(descriptor.get(key) != value for key, value in expected_node.items()):
                return unknown_receiver(binding, reason="receiver_binding_changed")
        result = read(binding)
        # A Python callback is not a reason to bypass wire validation.
        snapshot = ReceiverSnapshot.model_validate_json(
            result.model_dump_json() if isinstance(result, ReceiverSnapshot) else
            json.dumps(result))
        if ((snapshot.receiver_id, snapshot.address, snapshot.binding_epoch,
             snapshot.capability_scope.execution_host_ref) !=
                (binding.receiver_id, binding.actor_address, binding.binding_epoch,
                 binding.execution_host_ref)):
            return unknown_receiver(binding, reason="receiver_binding_changed")
        # Recovery actions are a Core authorization decision, not a capability
        # asserted by a receiver. They are populated by the action service only.
        return snapshot.current(now(), scope=snapshot.capability_scope).model_copy(
            update={"allowed_actions": ()})
    except Exception:  # noqa: BLE001 - observations never prepare/repair a receiver.
        return unknown_receiver(binding, reason="receiver_observation_unavailable")
