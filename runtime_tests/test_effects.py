from __future__ import annotations

import pytest

from runtime.effects import EffectGateway
from runtime.errors import EffectUnavailable


class Fence:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, int, str]] = []

    def verify_fence(self, lease_id: str, resource_id: str, generation: int, fencing_token: str) -> None:
        self.calls.append((lease_id, resource_id, generation, fencing_token))


def test_effect_gateway_fails_closed_after_fence_without_reader() -> None:
    fence = Fence()
    gateway = EffectGateway(fence)

    with pytest.raises(EffectUnavailable):
        gateway.verify_and_readback("lease-1", "resource-1", 2, "token-1", "caller-supplied")

    assert fence.calls == [("lease-1", "resource-1", 2, "token-1")]
