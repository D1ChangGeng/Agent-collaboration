from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from runtime.migrations import (
    FOUNDATION_HASH_VERSION,
    HARDENED_HASH_VERSION,
    LegacyCommandRecord,
    classify_replay,
    legacy_command_hash,
    migrate_legacy_record,
    recover_original_command_id,
)

# Computed by executing only _hash from the pinned e55d9d7 and 912b19b sources.
FROZEN_HASHES = {
    FOUNDATION_HASH_VERSION: "4297e93707bb4cb994bdbabf574dcfdfe42d8d085c8f950bd170adbee592d6ec",
    HARDENED_HASH_VERSION: "1463311f7d7c019646c224298c9c0427960c75ad4eba35eed91eede0126021b2",
}
EXTRA = {"scope_id": "local-scope"}


def command(**updates):
    now = datetime(2026, 9, 11, tzinfo=UTC)
    values = {
        "command_id": "cmd-original", "command_type": "work_item.create",
        "idempotency_key": "idem-legacy", "correlation_id": "corr", "causation_id": None,
        "tenant_id": "tenant", "authority_id": "auth", "authority_incarnation": "inc",
        "principal_ref": "agent", "grant_ref": "grant", "target_kind": "work_item",
        "target_id": "work", "expected_revision": 0, "issued_at": now,
        "deadline": now + timedelta(minutes=1), "payload": {"label": "migration"},
    }
    values.update(updates)
    return SimpleNamespace(**values)


def record(**updates):
    values = {
        "tenant_id": "tenant", "idempotency_key": "idem-legacy", "command_id": None,
        "payload_hash": FROZEN_HASHES[HARDENED_HASH_VERSION],
        "result_json": {"command_id": "cmd-original"}, "hash_version": None,
        "principal_ref": "agent",
    }
    values.update(updates)
    return LegacyCommandRecord(**values)


@pytest.mark.parametrize("version", tuple(FROZEN_HASHES))
def test_hash_matches_pinned_source_vector(version):
    assert legacy_command_hash(command(), EXTRA, hash_version=version) == FROZEN_HASHES[version]


@pytest.mark.parametrize("version", tuple(FROZEN_HASHES))
@pytest.mark.parametrize("record_version", (None, "v1", "legacy-unclassified"))
def test_unclassified_rows_identify_the_actual_historical_algorithm(version, record_version):
    row = record(payload_hash=FROZEN_HASHES[version], hash_version=record_version)
    assert migrate_legacy_record(row).action == "verify"
    result = classify_replay(row, command(), extra=EXTRA)
    assert result.action == "replay"
    assert result.command_id == "cmd-original"
    assert result.hash_version == version


@pytest.mark.parametrize("result", ({"command_id": 42}, {"command_id": None},
                                    {"command_id": "   "}, {"command_id": "x\n"},
                                    {"command_id": "x" * 257}, [], "not json"))
def test_malformed_result_does_not_fall_back_to_valid_column(result):
    row = record(command_id="cmd-original", result_json=result)
    assert recover_original_command_id(row) is None
    assert migrate_legacy_record(row).action == "quarantine"


def test_exact_recorded_identity_is_preserved_without_trimming():
    row = record(command_id=" cmd-original ", result_json={"command_id": " cmd-original "})
    assert recover_original_command_id(row) == " cmd-original "


def test_identity_conflict_and_idempotency_only_are_quarantined():
    assert recover_original_command_id(record(command_id="different")) is None
    assert recover_original_command_id(record(command_id=None, result_json={})) is None
    assert recover_original_command_id(record(command_id="idem-legacy", result_json={})) is None
    assert recover_original_command_id(record(command_id="cmd-original", result_json={})) == "cmd-original"


@pytest.mark.parametrize("field,value", (
    ("command_id", "other"), ("tenant_id", "other"),
    ("idempotency_key", "other"), ("principal_ref", "other"),
    ("causation_id", "unrecorded-cause"), ("payload", {"label": "changed"}),
))
def test_foundation_hash_cannot_bypass_identity_or_provenance_checks(field, value):
    row = record(payload_hash=FROZEN_HASHES[FOUNDATION_HASH_VERSION])
    assert classify_replay(row, command(**{field: value}), extra=EXTRA).action == "quarantine"


def test_foundation_replay_requires_independent_principal_provenance():
    row = record(payload_hash=FROZEN_HASHES[FOUNDATION_HASH_VERSION], principal_ref=None)
    assert classify_replay(row, command(), extra=EXTRA).reason == "missing_legacy_principal_provenance"


@pytest.mark.parametrize("digest", (None, "", "f" * 63, "F" * 64))
def test_missing_or_malformed_hash_is_not_replayable(digest):
    assert migrate_legacy_record(record(payload_hash=digest)).action == "quarantine"


def test_wrong_hash_wrong_algorithm_and_unknown_version_are_quarantined():
    base = record()
    for row in (
        replace(base, payload_hash="f" * 64),
        replace(base, hash_version="v9"),
        replace(base, payload_hash=FROZEN_HASHES[FOUNDATION_HASH_VERSION],
                hash_version=HARDENED_HASH_VERSION),
    ):
        assert classify_replay(row, command(), extra=EXTRA).action == "quarantine"


def test_current_rows_are_routed_to_current_dedup_without_legacy_replay():
    assert classify_replay(record(hash_version="v2"), command(), extra=EXTRA).action == "conflict"

@pytest.mark.parametrize("version", ("", "2"))
def test_undefined_version_aliases_are_quarantined(version):
    assert migrate_legacy_record(record(hash_version=version)).action == "quarantine"


@pytest.mark.parametrize("result", (None, {"command_id": "x" + chr(133)}))
def test_null_result_and_c1_controls_are_quarantined(result):
    assert migrate_legacy_record(record(command_id="cmd-original", result_json=result)).action == "quarantine"
