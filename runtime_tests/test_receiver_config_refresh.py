"""Trusted endpoint refresh preserves cache, identity and read-only boundaries."""
import json
from dataclasses import replace
from types import SimpleNamespace

import pytest

from runtime.machine_connections import ConfiguredRemoteEndpoint
from runtime.surface_config import ConfigurationError, configured_service
from runtime_tests.test_receiver_peer_continuity import peer as peer_fixture
from runtime_tests.test_surfaces import profile

peer = peer_fixture


def test_generation_change_invalidates_cached_adapter_without_registration_change(peer, monkeypatch):
    import runtime.machine_connections as module
    monkeypatch.setenv('ACS_TEST_REFRESH_KEY', peer.authority_key.encode().hex())
    original = peer.settings.model_copy(update={"authority_signing_key_ref": peer.settings.authority_signing_key_ref.model_copy(
        update={"name": "ACS_TEST_REFRESH_KEY"})})
    current = {'value': original}
    authority = peer.authority
    deployments = []

    def adapter(_authority, _endpoint, deployment, *, timeout):
        deployments.append(deployment)
        config = replace(peer.config, journal_generation=deployment.journal_generation,
            old_boot_isolation_ref=deployment.old_boot_isolation_ref)
        config.validate()
        return SimpleNamespace(generation=deployment.journal_generation, config=config)

    monkeypatch.setattr(module, 'RemoteNodeEndpointAdapter', adapter)
    endpoint = ConfiguredRemoteEndpoint(authority, original, settings_provider=lambda _: current['value'])
    first = endpoint._adapter()
    assert first.generation == 1 and endpoint._adapter() is first
    current['value'] = original.model_copy(update={'journal_generation': 2, 'old_boot_isolation_ref': 'actual-stop-proof'})
    second = endpoint._adapter()
    assert second is not first and second.generation == 2
    assert deployments[-1].old_boot_isolation_ref == 'actual-stop-proof' and len(deployments) == 2


def configured(tmp_path, monkeypatch):
    config, env, _secret = profile(tmp_path, dsn='postgresql://fixture:fixture@127.0.0.1:1/isolated_test',
        extra={'remote_endpoints': [{'endpoint_id': 'endpoint',
            'authority_signing_key_ref': {'kind': 'environment', 'name': 'ACS_TEST_REFRESH_KEY'}}]})
    for name in ('ACS_TEST_SURFACE_DSN', 'ACS_TEST_SURFACE_TOKEN'):
        monkeypatch.setenv(name, env[name])
    return config


def test_live_service_reloads_its_private_file_without_rebinding_identity(tmp_path, monkeypatch):
    config = configured(tmp_path, monkeypatch)
    with configured_service(config) as (service, _settings):
        endpoint = service.authority._delivery_endpoints['endpoint']
        value = json.loads(config.read_text())
        value['remote_endpoints'][0].update(journal_generation=2, old_boot_isolation_ref='verified-stop')
        config.write_text(json.dumps(value))
        endpoint._refresh_settings()
        assert endpoint.settings.journal_generation == 2
        assert endpoint.settings.old_boot_isolation_ref == 'verified-stop'


@pytest.mark.parametrize('change', ['identity', 'access_mode', 'dsn', 'dsn_value', 'credential', 'endpoint_removed'])
def test_private_refresh_requires_reconnection_for_changed_identity(tmp_path, monkeypatch, change):
    config = configured(tmp_path, monkeypatch)
    with configured_service(config) as (service, _settings):
        endpoint = service.authority._delivery_endpoints['endpoint']
        value = json.loads(config.read_text())
        if change == 'identity':
            value['context']['principal_ref'] = 'a-different-subject'
        elif change == 'access_mode':
            value['access_mode'] = 'owner'
        elif change == 'dsn':
            value['dsn_ref']['name'] = 'ACS_TEST_OTHER_DSN'
            monkeypatch.setenv('ACS_TEST_OTHER_DSN', 'postgresql://fixture:fixture@127.0.0.1:2/other')
        elif change == 'dsn_value':
            monkeypatch.setenv('ACS_TEST_SURFACE_DSN', 'postgresql://fixture:fixture@127.0.0.1:2/other')
        elif change == 'credential':
            value['credential_ref']['name'] = 'ACS_TEST_OTHER_TOKEN'
        else:
            value['remote_endpoints'] = []
        config.write_text(json.dumps(value))
        with pytest.raises(ConfigurationError):
            endpoint._refresh_settings()
        assert endpoint.settings.journal_generation == 1


def test_status_does_not_prepare_when_refresh_cannot_be_authorized(monkeypatch):
    def unavailable(_endpoint):
        raise ConfigurationError('must reconnect')
    endpoint = ConfiguredRemoteEndpoint(SimpleNamespace(), SimpleNamespace(endpoint_id='endpoint'),
        settings_provider=unavailable)
    calls = []
    monkeypatch.setattr(endpoint, '_prepare', lambda: calls.append('prepare'))
    assert endpoint.inspect_runtime()['state'] == 'offline'
    assert calls == []
