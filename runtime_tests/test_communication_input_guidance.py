"""Public corrective guidance must retain admission and no-side-effect boundaries."""
import json

import psycopg
import pytest

from runtime.mcp_runtime import McpRuntime
from runtime_tests.test_communication import comm as comm_fixture

comm = comm_fixture


def test_missing_arguments_can_be_corrected_without_a_failed_send_side_effect(comm):
    client = comm.clients['a']
    args = {}
    for field, value in (
        ('project_id', 'project-alpha'),
        ('to', 'collaborator:project-alpha:slot-b'),
        ('content', 'An ordinary corrected request'),
    ):
        rejected = client.call('send_message', args)['structuredContent']
        assert rejected['data']['code'] == 'invalid_arguments'
        assert rejected['data']['field'] == field
        assert field in rejected['data']['guidance']
        with psycopg.connect(comm.dsn) as connection:
            assert connection.execute('SELECT count(*) FROM communication_messages').fetchone() == (0,)
        args[field] = value
    result = client.call('send_message', {**args, 'activation': 'message_only'})['structuredContent']
    assert result['ok']
    retained = client.call('read_message', {'project_id': 'project-alpha',
        'handle': result['data']['message_handle']})['structuredContent']
    assert retained['ok'] and retained['data']['content'] == args['content']
    with psycopg.connect(comm.dsn) as connection:
        assert connection.execute('SELECT count(*) FROM communication_messages').fetchone() == (1,)
    assert not any(driver.calls for driver in comm.drivers.values())


@pytest.mark.parametrize(('args', 'field'), [
    ({'limit': True}, 'limit'),
    ({'direction': 'newest'}, 'direction'),
    ({'limit': 0}, 'limit'),
    ({'limit': 101}, 'limit'),
    ({'from': 'forged-private-value'}, '$'),
])
def test_schema_guidance_is_bounded_and_does_not_echo_values(comm, args, field):
    result = comm.clients['a'].call('list_messages', {'project_id': 'project-alpha', **args})['structuredContent']
    assert result['data']['code'] == 'invalid_arguments'
    assert result['data']['field'] == field and result['data']['guidance']
    assert 'forged-private-value' not in json.dumps(result)


def test_hidden_tool_and_invalid_credentials_do_not_disclose_corrective_fields(comm):
    client = comm.clients['b']
    hidden = client.call('configure_team', {})['structuredContent']
    assert hidden['data']['code'] == 'authorization_denied'
    assert 'field' not in hidden['data'] and 'guidance' not in hidden['data']
    rejected = McpRuntime(client.service, lambda: 'wrong-credential').call('send_message', {})['structuredContent']
    assert rejected['data']['code'] == 'authorization_denied'
    assert 'field' not in rejected['data'] and 'guidance' not in rejected['data']


def test_unavailable_guidance_discovery_is_not_reported_as_permission_denial(comm, monkeypatch):
    def unavailable(_credential):
        raise RuntimeError('private-backend-detail')
    monkeypatch.setattr(comm.clients['a'].service, 'available_tools', unavailable)
    result = comm.clients['a'].call('send_message', {})['structuredContent']
    assert result['data']['code'] == 'service_unavailable' and result['data']['retryable']
    assert 'field' not in result['data'] and 'private-backend-detail' not in json.dumps(result)


@pytest.mark.parametrize('content', ['   ', '🙂' * 8193], ids=['whitespace', 'oversize_utf8'])
def test_invalid_message_content_names_the_field_without_echoing_it(comm, content):
    result = comm.clients['a'].call('send_message', {'project_id': 'project-alpha',
        'to': 'collaborator:project-alpha:slot-b', 'content': content})['structuredContent']
    assert result['data']['field'] == 'content' and result['data']['code'] == 'invalid_arguments'
    assert '32768' in result['data']['guidance']
    with psycopg.connect(comm.dsn) as connection:
        assert connection.execute('SELECT count(*) FROM communication_messages').fetchone() == (0,)


@pytest.mark.parametrize('content', ['🙂' * 8192, '汉' * 10922], ids=['emoji_boundary', 'chinese_boundary'])
def test_valid_unicode_message_uses_utf8_bytes_and_retains_original_content(comm, content):
    assert len(content.encode('utf-8')) <= 32768
    result = comm.clients['a'].call('send_message', {'project_id': 'project-alpha',
        'to': 'collaborator:project-alpha:slot-b', 'content': content,
        'activation': 'message_only'})['structuredContent']
    assert result['ok'], result
    observed = comm.clients['b'].call('read_message', {'project_id': 'project-alpha',
        'handle': result['data']['message_handle'], 'max_inline_bytes': 65536})['structuredContent']
    assert observed['ok'] and observed['data']['content'] == content
    assert not any(driver.calls for driver in comm.drivers.values())
