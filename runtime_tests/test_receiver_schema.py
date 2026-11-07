"""Published JSON schema and generated SDK must match the implemented contracts."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, FormatChecker
from jsonschema.exceptions import ValidationError

from runtime_tests.test_receiver_contract import snapshot
from tools.runtime.export_receiver_contracts import schema, typescript

ROOT = Path(__file__).resolve().parents[1]


def test_schema_and_sdk_are_reproducible_and_validate_a_receiver():
    actual = json.loads((ROOT / "docs/runtime/receiver-evidence.schema.json").read_text(encoding="utf-8"))
    assert actual == schema()
    assert (ROOT / "sdk/receiver-evidence.ts").read_text(encoding="utf-8") == typescript(actual)
    Draft202012Validator.check_schema(actual)
    Draft202012Validator(actual, format_checker=FormatChecker()).validate(snapshot().model_dump(mode="json"))


@pytest.mark.parametrize("change", [
    {"support": "supported", "evidence_ref": None},
    {"support": "unknown", "availability": "available"},
    {"support": "unsupported", "availability": "available"},
    {"name": "brand-derived-support"},
])
def test_published_schema_rejects_unproven_capability_claims(change):
    item = snapshot().model_dump(mode="json")
    item["capabilities"][0].update(change)
    with pytest.raises(ValidationError):
        Draft202012Validator(schema()).validate(item)


@pytest.mark.parametrize("change", [{"knowledge": "unknown"}, {"source": "pty_heuristic"},
    {"observed_at": None}, {"evidence_ref": None}, {"source": "none"}])
def test_published_schema_rejects_fabricated_observation_evidence(change):
    item = snapshot().model_dump(mode="json")
    item["observations"][0].update(change)
    with pytest.raises(ValidationError):
        Draft202012Validator(schema(), format_checker=FormatChecker()).validate(item)


def test_published_schema_requires_unknown_input_to_keep_possible_effect():
    item = {"schema_version": "acs-adapter/1", "operation_id": "operation", "outcome": "unknown",
        "effect_possible": False, "evidence_ref": None, "native_input_ref": None,
        "binding_epoch": 1, "provider_generation": "generation", "reason_code": "ack_lost"}
    with pytest.raises(ValidationError):
        Draft202012Validator(schema()).validate(item)
