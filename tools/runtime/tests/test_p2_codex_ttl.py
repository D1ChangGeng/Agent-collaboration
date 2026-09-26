from __future__ import annotations

import pytest

from tools.runtime.p2_codex_half_loop import MAX_ENDPOINT_TTL_SECONDS, endpoint_ttl_seconds


def test_endpoint_ttl_is_bounded_by_node_proof_ceiling():
    assert MAX_ENDPOINT_TTL_SECONDS == 300
    assert endpoint_ttl_seconds("300") == 300

    for value in ("0", "301", "1800", "not-a-number"):
        with pytest.raises(Exception):
            endpoint_ttl_seconds(value)
