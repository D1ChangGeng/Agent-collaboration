import hashlib
import json
from copy import deepcopy
from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from runtime.connection_clock import presentation_metadata
from runtime.models import CommandEnvelope
from runtime.surface_config import SurfaceSettings


def command(**updates):
    return CommandEnvelope(
        command_id="command", command_type="work.create", idempotency_key="identity",
        correlation_id="correlation", tenant_id="tenant", authority_id="authority",
        authority_incarnation="incarnation", principal_ref="principal", grant_ref="grant",
        target_kind="work_item", target_id="work", expected_revision=0,
        issued_at=updates.pop("issued_at", datetime(2026, 1, 1, tzinfo=timezone(timedelta(hours=9)))),
        deadline=updates.pop("deadline", datetime(2026, 1, 1, 1, tzinfo=timezone(timedelta(hours=9)))),
        **updates,
    )


def test_timezone_awareness_preserves_historical_offset_hash_encoding():
    original = command()
    assert original.model_dump(mode="json")["issued_at"].endswith("+09:00")
    historical_bytes = json.dumps(original.model_dump(mode="json"), sort_keys=True, separators=(",", ":")).encode()
    assert original.canonical_hash() == hashlib.sha256(historical_bytes).hexdigest()
    replay = CommandEnvelope.model_validate_json(original.model_dump_json(), strict=True)
    assert replay.canonical_hash() == original.canonical_hash()
    assert replay.legacy_hash() == original.legacy_hash()


@pytest.mark.parametrize("field", ["issued_at", "deadline"])
def test_naive_command_time_is_rejected_before_mixed_awareness_comparison(field):
    with pytest.raises(ValidationError, match="explicit timezone"):
        command(**{field: datetime.fromisoformat("2026-01-01T00:00:00")})


def test_presentation_sidecar_leaves_signed_and_canonical_inputs_unchanged():
    data = {"items": [{"created_at": "2026-01-01T00:00:00Z", "deadline": "2026-01-01T01:00:00Z"}],
            "signed_request": command().model_dump(mode="json")}
    old = deepcopy(data)
    digest = command().canonical_hash()
    output = presentation_metadata(data, "Asia/Tokyo")
    assert output["timestamps"]["/items/0/created_at"]["display"] == "2026-01-01T09:00:00+09:00"
    assert output["timestamps"]["/items/0/created_at"]["canonical_utc"] == "2026-01-01T00:00:00+00:00"
    assert data == old
    assert command().canonical_hash() == digest


def test_presentation_ignores_naive_values_and_is_bounded():
    data = {"items": [{"observed_at": "2026-01-01T00:00:00+00:00"} for _ in range(200)],
            "created_at": "2026-01-01T00:00:00"}
    result = presentation_metadata(data)
    assert len(result["timestamps"]) <= 100
    assert "/created_at" not in result["timestamps"]


def test_configured_iana_timezone_does_not_change_authority_configuration():
    base = {
        "context": {"tenant_id": "tenant", "authority_id": "authority",
                    "authority_incarnation": "incarnation", "principal_ref": "principal",
                    "grant_ref": "grant", "credential_hash": "a" * 64},
        "dsn_ref": {"kind": "environment", "name": "TEST_DSN"},
        "credential_ref": {"kind": "environment", "name": "TEST_CREDENTIAL"},
    }
    utc = SurfaceSettings.model_validate(base)
    tokyo = SurfaceSettings.model_validate({**base, "presentation_timezone": "Asia/Tokyo"})
    assert utc.presentation_timezone == "UTC"
    assert tokyo.context == utc.context
    assert tokyo.dsn_ref == utc.dsn_ref
    with pytest.raises(ValidationError, match="IANA timezone"):
        SurfaceSettings.model_validate({**base, "presentation_timezone": "invalid/unsupported"})


def test_unrenderable_extreme_timestamp_does_not_escape_display_sidecar():
    result = presentation_metadata({"completed_at": "9999-12-31T23:59:59+00:00"}, "Asia/Tokyo")
    assert result["timestamps"] == {}
