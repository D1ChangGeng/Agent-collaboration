from __future__ import annotations

from datetime import UTC, datetime
from typing import Protocol


class FenceAuthority(Protocol):
    def verify_fence(self, lease_id: str, resource_id: str, generation: int, fencing_token: str) -> None: ...


class EffectGateway:
    def __init__(self, authority: FenceAuthority) -> None:
        self._authority = authority

    def verify_and_readback(self, lease_id: str, resource_id: str, generation: int, fencing_token: str, readback_ref: str) -> dict[str, str]:
        self._authority.verify_fence(lease_id, resource_id, generation, fencing_token)
        return {"resource_id": resource_id, "readback_ref": readback_ref, "observed_at": datetime.now(UTC).isoformat()}
