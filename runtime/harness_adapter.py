"""Cross-language Adapter 1 boundary; authorization stays in the existing Core/Node.

Implementations must verify the original sealed receiver envelope before trusting
any outer wire field. Discovery/observation/reconciliation must not admit input.
Unsupported optional behavior is explicit, never simulated by terminal typing.
"""
from __future__ import annotations

from typing import Protocol

from runtime.receiver_contract import (
    NativeAdmissionCommand,
    NativeAdmissionResult,
    Observation,
    ReceiverBinding,
    ReceiverSnapshot,
)
from runtime.signed_harness_adapter import ReadOnlySignedHarnessAdapter, SignedHarnessAdapter

__all__ = ["HarnessAdapter", "ReadOnlySignedHarnessAdapter", "SignedHarnessAdapter"]


class HarnessAdapter(Protocol):
    async def describe(self, binding: ReceiverBinding) -> ReceiverSnapshot: ...

    async def observe(self, binding: ReceiverBinding) -> tuple[Observation, ...]: ...

    async def admit_input(self, command: NativeAdmissionCommand) -> NativeAdmissionResult: ...

    async def reconcile(self, operation_id: str, binding: ReceiverBinding) -> NativeAdmissionResult: ...
