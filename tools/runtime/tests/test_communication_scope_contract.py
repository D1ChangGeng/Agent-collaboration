"""Delivery scope checks; these do not qualify a running Runtime or Native Host."""
from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from pathlib import Path

import pytest
import yaml

from tools.runtime.export_p1_openapi import build_contract, render

ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture
def contracts():
    full = yaml.safe_load((ROOT / "docs/client/communication-openapi.yaml").read_text(encoding="utf-8"))
    scope = json.loads((ROOT / "docs/client/communication-api-scope.json").read_text(encoding="utf-8"))
    return full, scope


def test_scope_is_the_adopted_revision_with_complete_unchanged_operation_mapping(contracts):
    _full, scope = contracts
    original = ROOT / "RFC_TEMP_SOURCE/ACS-Core-Stage-Agnostic-Revision-Pack-v1.1.0/contracts/api-scope.json"
    assert hashlib.sha256(original.read_bytes()).hexdigest() == scope["source_contract_sha256"]
    assert scope["operations"] == json.loads(original.read_text(encoding="utf-8"))["operations"]
    assert scope["revision_package_version"] == "1.1.0"


def test_p1_export_retains_all_22_required_operations_without_expanding_optional_scope(contracts):
    full, scope = contracts
    before = deepcopy(full)
    exported = build_contract(full, scope)
    expected = {item["operation_id"] for item in scope["operations"] if item["tier"] == "P1_required"}
    observed = {value["operationId"] for methods in exported["paths"].values()
                for value in methods.values() if isinstance(value, dict) and "operationId" in value}
    assert len(expected) == 22 and observed == expected
    assert full == before  # The original full API, including P2, remains intact.
    assert (ROOT / "docs/client/communication-p1-openapi.yaml").read_text(encoding="utf-8") == render()


def test_p1_projection_does_not_require_personal_state_or_binary_attachment_fields(contracts):
    schemas = build_contract(*contracts)["components"]["schemas"]
    for name, fields in {"Conversation": {"unread_count", "archived", "muted"},
                         "Message": {"attachment_refs"}, "Notice": {"seen"}}.items():
        assert not fields.intersection(schemas[name].get("required", []))
        # Compatible optional data remains expressible when the server provides it.
        assert fields <= schemas[name]["properties"].keys()


@pytest.mark.parametrize("defect", ["missing", "duplicate", "route", "tier"])
def test_scope_drift_fails_closed_before_export(contracts, defect):
    full, scope = contracts
    if defect == "missing":
        scope["operations"].pop()
    elif defect == "duplicate":
        scope["operations"].append(deepcopy(scope["operations"][0]))
    elif defect == "route":
        scope["operations"][0]["path"] = "/foreign-contract"
    else:
        scope["operations"][0]["tier"] = "P2_optional"
    with pytest.raises(ValueError):
        build_contract(full, scope)
