"""Fail-closed profile checks; real binary evidence lives in Native qualification."""
import json
import sys
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from runtime.codex_driver import CodexAppServerDriver, DriverRejected, LaunchProfile, file_digest
from runtime.communication_tools import NATIVE_COLLABORATION_TOOLS

FLAGS = ("multi_agent", "multi_agent_v2", "shell_tool", "request_permissions_tool", "apps", "plugins")


@pytest.fixture
def shared(tmp_path):
    config = tmp_path / "config.toml"
    config.write_text('\n'.join([
        'default_permissions="achp-engineer"', 'approval_policy="never"', '[features]',
        *[name+'=false' for name in FLAGS], '[permissions.achp-engineer.filesystem]',
        '":minimal"="read"', json.dumps(str(tmp_path))+'="read"', json.dumps(sys.executable)+'="read"',
        '[permissions.achp-engineer.network]', 'enabled=false', '[mcp_servers.acs]',
        'command='+json.dumps(sys.executable), 'required=true',
        'enabled_tools='+json.dumps(list(NATIVE_COLLABORATION_TOOLS)),
    ]))
    schema = tmp_path / 'schema.json'
    schema.write_text('{}')
    return LaunchProfile(sys.executable, file_digest(sys.executable), '0.163.0', str(schema), file_digest(schema),
                         str(tmp_path), str(tmp_path), file_digest(config), 'achp-engineer', {}, collaboration_server='acs')


def test_exact_codex_shared_profile(shared):
    assert shared.validate() is shared


@pytest.mark.parametrize('change', ['writable', 'network', 'delegation', 'extra_mcp', 'extra_tool', 'overrides', 'proxy'])
def test_codex_shared_rejects_expanded_authority(shared, change):
    path = Path(shared.codex_home) / 'config.toml'
    text = path.read_text()
    if change == 'writable': text = text.replace('="read"', '="write"', 1)
    if change == 'network': text = text.replace('enabled=false', 'enabled=true')
    if change == 'delegation': text = text.replace('multi_agent=false', 'multi_agent=true')
    if change == 'extra_mcp': text += '\n[mcp_servers.other]\ncommand="/bin/true"\n'
    if change == 'extra_tool': text = text.replace('"wait_for_response"', '"wait_for_response", "execute"')
    path.write_text(text)
    profile = replace(shared, config_sha256=file_digest(path))
    if change == 'overrides': profile = replace(profile, startup_overrides=('features.multi_agent=true',))
    if change == 'proxy': profile = replace(profile, environment={'HTTPS_PROXY': 'http://127.0.0.1:1'})
    with pytest.raises(DriverRejected): profile.validate()


@pytest.mark.parametrize('fault', [None, 'feature_missing', 'feature_enabled', 'network', 'profile', 'mcp_missing', 'mcp_extra', 'mcp_disconnected', 'mcp_error'])
def test_codex_shared_requires_positive_native_readback(shared, fault):
    tools = {name: {} for name in NATIVE_COLLABORATION_TOOLS if name != 'list_projects'}
    features = [{'name': name, 'enabled': False} for name in FLAGS]
    response = {'cwd': shared.cwd, 'approvalPolicy': 'never', 'activePermissionProfile': {'id': 'achp-engineer'},
                'sandbox': {'type': 'readOnly', 'networkAccess': False}}
    server = {'name': 'acs', 'runtimeStatus': 'connected', 'tools': tools}
    if fault == 'feature_missing': features.pop()
    if fault == 'feature_enabled': features[0]['enabled'] = True
    if fault == 'network': response['sandbox']['networkAccess'] = True
    if fault == 'mcp_missing': tools.pop('send_message')
    if fault == 'mcp_extra': tools['execute'] = {}
    if fault == 'mcp_disconnected': server['runtimeStatus'] = 'connecting'
    if fault == 'mcp_error': server['toolsError'] = 'discovery unavailable'
    calls = []
    def rpc(operation, method, params):
        calls.append((method, params))
        if method == 'experimentalFeature/list': return {'data': features}
        if method == 'permissionProfile/list': return {'data': [{'id': 'achp-engineer', 'allowed': fault != 'profile'}]}
        if method == 'mcpServerStatus/list': return {'data': [server]}
        raise AssertionError(method)
    driver = SimpleNamespace(profile=shared, thread_id='actual-thread', _rpc=rpc)
    if fault is None:
        CodexAppServerDriver._settings(driver, None, response)
        assert 'threadId' not in calls[0][1]
        assert calls[-1][1]['threadId'] == 'actual-thread'
    else:
        with pytest.raises(DriverRejected): CodexAppServerDriver._settings(driver, None, response)
