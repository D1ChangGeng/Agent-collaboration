"""Attachment opt-in rejects capacity claims before opening files or services."""
from pathlib import Path

import pytest
from pydantic import ValidationError

from runtime.project_http import ProjectHttpSettings
from runtime.surface_config import CommunicationAttachmentSettings, SurfaceSettings


def surface(**changes):
    return {"context": {"tenant_id": "synthetic", "authority_id": "authority", "authority_incarnation": "one",
        "principal_ref": "actor", "grant_ref": "grant", "credential_hash": "a" * 64},
        "dsn_ref": {"kind": "environment", "name": "SYNTHETIC_ATTACHMENT_DSN"},
        "credential_ref": {"kind": "environment", "name": "SYNTHETIC_ATTACHMENT_CREDENTIAL"}, **changes}


def artifact(scope="local-scope", maximum=20 * 1024 * 1024):
    return {"root": str(Path.cwd() / ".tmp" / ("attachment-config-" + scope)), "scope_id": scope, "max_bytes": maximum}


def http(**changes):
    return {"issuer_url": "https://issuer.example.test", "resource_url": "https://runtime.example.test/mcp",
        "introspection_url": "https://issuer.example.test/introspect", "introspection_client_id": "synthetic",
        "introspection_secret_ref": {"kind": "environment", "name": "SYNTHETIC_INTROSPECTION_SECRET"},
        "bindings": ({"subject": "synthetic", "client_id": "synthetic", "principal_ref": "actor", "grant_ref": "grant", "profile": "agent"},),
        **changes}


def test_disabled_attachment_settings_preserve_existing_cas_capacity():
    value = SurfaceSettings.model_validate(surface(artifacts=artifact(maximum=16 * 1024 * 1024)), strict=True)
    assert value.communication_attachments is None and not value.communication_client_api
    assert not ProjectHttpSettings.model_validate(http(), strict=True).communication_attachments


def test_enabled_attachment_configuration_requires_actual_explicit_scope_capacity():
    valid = surface(communication_client_api=True, communication_attachments={}, artifacts=artifact())
    settings = SurfaceSettings.model_validate(valid, strict=True)
    assert settings.communication_attachments.file_bytes == settings.artifacts.max_bytes == 20 * 1024 * 1024
    assert settings.communication_attachments.message_count == 8
    assert settings.communication_attachments.message_bytes == 50 * 1024 * 1024
    limits = settings.communication_attachments.to_limits()
    assert limits.file_bytes == 20 * 1024 * 1024 and limits.attachments_per_message == 8
    assert limits.viewer_bytes == 100 * 1024 * 1024 and limits.project_bytes == 1024 * 1024 * 1024
    assert limits.chunk_bytes == 65536 and limits.reservation_ttl_seconds == 24 * 3600
    for changes in ({"communication_client_api": False}, {"artifacts": None},
                    {"artifacts": artifact(maximum=16 * 1024 * 1024)},
                    {"additional_artifacts": (artifact("route", maximum=16 * 1024 * 1024),)}):
        with pytest.raises(ValidationError):
            SurfaceSettings.model_validate(valid | changes, strict=True)


def test_attachment_http_opt_in_cannot_exist_without_client_facade():
    with pytest.raises(ValidationError):
        ProjectHttpSettings.model_validate(http(communication_attachments=True), strict=True)
    assert ProjectHttpSettings.model_validate(http(communication_client_api=True, communication_attachments=True), strict=True).communication_attachments


@pytest.mark.parametrize("field", ["message_bytes", "viewer_staging_bytes", "project_staging_bytes"])
def test_reservation_budgets_cannot_advertise_a_file_that_they_cannot_admit(field):
    with pytest.raises(ValidationError):
        CommunicationAttachmentSettings.model_validate({field: 20 * 1024 * 1024 - 1}, strict=True)


@pytest.mark.parametrize("value", [True, "20971520", 0, 256 * 1024 * 1024 + 1])
def test_attachment_file_limit_is_explicit_bounded_integer(value):
    with pytest.raises(ValidationError):
        CommunicationAttachmentSettings.model_validate({"file_bytes": value}, strict=True)
