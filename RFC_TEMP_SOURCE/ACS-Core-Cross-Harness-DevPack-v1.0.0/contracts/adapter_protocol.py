"""Target ACS Adapter Protocol 1. Definitions only; not an ACS implementation.
Trusted envelopes are issued by Core/Node after authentication, never by message text.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import AsyncIterator, Literal, Mapping, Protocol, Sequence

Knowledge = Literal["observed", "inferred", "unknown", "unsupported"]
Support = Literal["supported", "unsupported", "unknown"]
Availability = Literal["available", "temporarily_unavailable", "unknown"]
OutcomeKind = Literal["accepted", "queued", "definitively_not_admitted", "unknown", "unsupported"]

@dataclass(frozen=True)
class ReceiverBinding:
    receiver_id: str
    actor_address: str
    binding_epoch: int
    provider_generation: str | None
    native_session_ref: str | None
    authority_id: str
    authority_incarnation: str
    execution_host_ref: str

@dataclass(frozen=True)
class Capability:
    name: str
    support: Support
    availability: Availability
    evidence_ref: str | None
    valid_until: str | None
    conditions: tuple[str, ...] = ()

@dataclass(frozen=True)
class CapabilityManifest:
    protocol: Literal["acs-adapter/1"]
    adapter_id: str
    adapter_version: str
    harness_kind: str
    harness_version: str | None
    binary_digest: str | None
    config_digest: str | None
    binding: ReceiverBinding
    capabilities: tuple[Capability, ...]

@dataclass(frozen=True)
class Observation:
    axis: Literal["connection", "process", "session", "input", "blocker"]
    knowledge: Knowledge
    value: str | None
    source: Literal["authority", "native_api", "authenticated_hook", "pty_heuristic", "none"]
    observed_at: str | None
    expires_at: str | None
    evidence_ref: str | None
    binding: ReceiverBinding

@dataclass(frozen=True)
class TrustedInput:
    operation_id: str
    message_handles: tuple[str, ...]
    canonical_hash: str
    binding: ReceiverBinding
    sender_addresses: tuple[str, ...]
    auth_revision: str
    admission_token_ref: str
    content_reference: str
    input_mode: Literal["structured", "safe_queue", "terminal_pointer"]
    deadline: str | None
    # Receiver checks this signed envelope and current enrollment itself.
    sealed_envelope: bytes

@dataclass(frozen=True)
class InputOutcome:
    operation_id: str
    kind: OutcomeKind
    effect_possible: bool
    evidence_ref: str | None
    native_input_ref: str | None
    reason_code: str | None
    binding: ReceiverBinding
    # accepted/queued is native admission evidence, never a model reply.

@dataclass(frozen=True)
class PrepareCommand:
    operation_id: str
    binding: ReceiverBinding
    auth_revision: str
    permitted_mode: Literal["resume_existing", "create_receiver"]
    expected_binding_revision: int
    admission_token_ref: str

@dataclass(frozen=True)
class PrepareOutcome:
    operation_id: str
    kind: Literal["prepared", "refused", "unknown", "unsupported"]
    binding: ReceiverBinding
    evidence_ref: str | None
    reason_code: str | None

class HarnessAdapter(Protocol):
    async def describe(self, binding: ReceiverBinding) -> CapabilityManifest:
        """Read-only capability discovery; MUST NOT spawn/resume or create a Session."""
        ...
    async def observe(self, binding: ReceiverBinding) -> Sequence[Observation]:
        """Read-only, evidence-bearing state; silence cannot be promoted to idle."""
        ...
    async def admit_input(self, command: TrustedInput) -> InputOutcome:
        """Fence and journal before side effect. Duplicate ID replays original outcome."""
        ...
    async def reconcile(self, operation_id: str, binding: ReceiverBinding) -> InputOutcome:
        """Query the ORIGINAL operation; no new input or fabricated negative evidence."""
        ...

class PreparableAdapter(HarnessAdapter, Protocol):
    async def prepare_receiver(self, command: PrepareCommand) -> PrepareOutcome:
        """Optional authorized lifecycle action, distinct from read/observe."""
        ...

class ObservableAdapter(HarnessAdapter, Protocol):
    def subscribe_observations(self, binding: ReceiverBinding, cursor: str | None) -> AsyncIterator[Observation]:
        """Optional; bounded reconnect, source generation checks and no transcript harvesting."""
        ...
