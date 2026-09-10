from __future__ import annotations

from typing import Protocol

from runtime.errors import EffectUnavailable


class FenceAuthority(Protocol):
    def verify_fence(self, lease_id: str, resource_id: str, generation: int, fencing_token: str) -> None: ...


class EffectGateway:
    def __init__(self, authority: FenceAuthority) -> None:
        self._authority = authority

    def verify_and_readback(self, lease_id: str, resource_id: str, generation: int, fencing_token: str, readback_ref: str) -> dict[str, str]:
        self._authority.verify_fence(lease_id, resource_id, generation, fencing_token)
        raise EffectUnavailable(resource_id, "no protected resource reader is configured")
