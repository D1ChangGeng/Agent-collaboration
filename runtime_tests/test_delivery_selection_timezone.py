"""Persistent receiver selection compares instants while retaining exact source digests."""
from datetime import UTC, datetime

import pytest

from runtime.delivery import DeliveryDispatcher, DeliveryRejected, digest, selection_expiry


def test_binding_selection_uses_one_instant_across_connection_timezones():
    binding = {'revision': 1, 'scope_id': 'scope', 'agent_slot_id': 'slot', 'machine_id': 'machine',
        'node_id': 'node', 'boot_incarnation': 'boot', 'supports_invoke': True, 'evidence_class': 'native',
        'expires_at': '2026-11-08T21:23:34.773245+09:00'}
    local = DeliveryDispatcher._selection({'endpoint_id': 'endpoint'}, binding)
    binding['expires_at'] = datetime(2026, 11, 8, 12, 23, 34, 773245, tzinfo=UTC)
    canonical = DeliveryDispatcher._selection({'endpoint_id': 'endpoint'}, binding)
    assert local == canonical
    assert digest(local) == digest(canonical)


def test_legacy_selection_can_be_compared_without_rewriting_its_original_hash():
    original = {'expires_at': '2026-11-08T21:23:34.773245+09:00', 'revision': 1}
    source_digest = digest(original)
    comparable = {**original, 'expires_at': selection_expiry(original['expires_at'])}
    assert comparable['expires_at'] == '2026-11-08T12:23:34.773245+00:00'
    assert digest(original) == source_digest
    assert digest(comparable) != source_digest


def test_expiry_requires_an_absolute_instant_and_preserves_unbounded_bindings():
    assert selection_expiry(None) == selection_expiry('None') == 'None'
    with pytest.raises(DeliveryRejected, match='attempt_selection_expiry_invalid'):
        selection_expiry('2026-11-08T12:00:00')
