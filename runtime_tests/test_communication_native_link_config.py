"""Pure explicit NativeLink metadata capacity and HTTP opt-in contracts."""
import pytest
from pydantic import ValidationError

from runtime.project_http import ProjectHttpSettings
from runtime.surface_config import CommunicationNativeLinkSettings, SurfaceSettings
from runtime_tests.test_communication_attachment_config import http, surface


def test_native_link_defaults_do_not_enable_or_construct_a_provider():
    settings = SurfaceSettings.model_validate(surface(), strict=True)
    assert settings.communication_native_links is None
    assert ProjectHttpSettings.model_validate(http(), strict=True).communication_native_links is False


def test_explicit_native_link_limits_map_without_requiring_an_attachment_store():
    settings = SurfaceSettings.model_validate(surface(communication_client_api=True, communication_native_links={}), strict=True)
    limits = settings.communication_native_links.to_limits()
    assert limits.links_per_scope == 1024 and limits.history_per_link == 4096
    assert limits.requests_per_viewer == 16384 and limits.metadata_bytes == 65536
    assert settings.artifacts is None and settings.communication_attachments is None


def test_native_link_runtime_and_http_configuration_require_client_facade():
    with pytest.raises(ValidationError):
        SurfaceSettings.model_validate(surface(communication_native_links={}), strict=True)
    with pytest.raises(ValidationError):
        ProjectHttpSettings.model_validate(http(communication_native_links=True), strict=True)
    assert ProjectHttpSettings.model_validate(http(communication_client_api=True, communication_native_links=True), strict=True).communication_native_links


@pytest.mark.parametrize("field", ["links_per_scope", "history_per_link", "requests_per_viewer", "metadata_bytes"])
@pytest.mark.parametrize("invalid", [True, 0, "1", 10000001])
def test_native_link_capacity_is_a_bounded_explicit_integer(field, invalid):
    with pytest.raises(ValidationError):
        CommunicationNativeLinkSettings.model_validate({field: invalid}, strict=True)
