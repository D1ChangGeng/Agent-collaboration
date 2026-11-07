"""Operator-only switches, with no receiver or Native side effects."""
import pytest

from runtime.surface_config import RemoteEndpointSettings
from runtime_deployment.receiver_lifecycle import validate_lifecycle_settings


@pytest.mark.parametrize("value", [True, 1, "true"])
def test_message_wake_never_implicitly_enables_lifecycle_control(value):
    with pytest.raises(ValueError):
        RemoteEndpointSettings.model_validate({"endpoint_id":"endpoint", "authority_signing_key_ref":{
            "kind":"environment", "name":"TEST_WAKE_KEY"}, "message_wake":value})
    with pytest.raises(ValueError):
        validate_lifecycle_settings({"lifecycle_message_wake":value})


def test_message_wake_is_disabled_by_default_without_requiring_lifecycle_setup():
    value=RemoteEndpointSettings.model_validate({"endpoint_id":"endpoint", "authority_signing_key_ref":{
        "kind":"environment", "name":"TEST_WAKE_KEY"}})
    assert value.message_wake is False and value.lifecycle_control is False
    validate_lifecycle_settings({})
