from __future__ import annotations

import hashlib
import os
import sqlite3
import sys
from types import SimpleNamespace

import pytest

from tools.runtime import p1_profile_probe as probe
from tools.runtime.p1_native_multiagent import (
    NativeInventoryRejected,
    _copy_pinned,
    capture_codex_bootstrap,
    capture_opencode_bootstrap,
    codex_effective_inventory,
    opencode_effective_inventory,
    reject_host_enablement_request,
)

CODEX_CONFIG = b"""
approval_policy = "never"
default_permissions = "achp-engineer"
[features]
multi_agent = false
multi_agent_v2 = false
shell_tool = false
request_permissions_tool = false
apps = false
plugins = false
"""


def test_codex_actual_feature_readback_requires_both_delegation_flags_off():
    active = {
        "activePermissionProfile": {"id": "achp-engineer"},
        "approvalPolicy": "never", "cwd": "/tmp/cwd",
    }
    pages = [({"threadId": "thread", "limit": 100}, {
        "data": [
            {"name": "multi_agent", "enabled": False},
            {"name": "multi_agent_v2", "enabled": False},
        ],
    })]
    summary = codex_effective_inventory(
        CODEX_CONFIG, active, pages,
        permission_profile="achp-engineer", cwd="/tmp/cwd",
    )
    assert summary["multi_agent"] is False
    assert summary["multi_agent_v2"] is False
    assert summary["native_tool_inventory_exposed"] is False
    changed = [({"threadId": "thread", "limit": 100}, {
        "data": [
            {"name": "multi_agent", "enabled": True},
            {"name": "multi_agent_v2", "enabled": False},
        ],
    })]
    with pytest.raises(NativeInventoryRejected, match="delegation"):
        codex_effective_inventory(
            CODEX_CONFIG, active, changed,
            permission_profile="achp-engineer", cwd="/tmp/cwd",
        )
    with pytest.raises(NativeInventoryRejected, match="config"):
        codex_effective_inventory(
            CODEX_CONFIG.replace(b"multi_agent = false", b"multi_agent = true"),
            active, pages, permission_profile="achp-engineer", cwd="/tmp/cwd",
        )


def test_opencode_effective_agent_and_tool_inventory_deny_delegation():
    profile = SimpleNamespace(agent="observer", data_root="/tmp/data", temp_root="/tmp/temp")
    config = {
        "permission": {"*": "deny", "task": "deny"},
        "default_agent": "observer",
        "agent": {"observer": {"permission": {"*": "deny", "task": "deny"}}},
        "plugin": [], "mcp": {},
    }
    agents = [{"name": "observer", "permission": [
        {"permission": "*", "pattern": "*", "action": "deny"},
    ]}]
    tools = ["task", "bash", "read"]
    summary = opencode_effective_inventory(config, agents, tools, profile=profile)
    assert summary["task_tool_present_but_denied"]
    assert summary["effective_tool_count"] == 3
    allow_task = [{"name": "observer", "permission": agents[0]["permission"] + [
        {"permission": "task", "pattern": "*", "action": "allow"},
    ]}]
    with pytest.raises(NativeInventoryRejected, match="unreviewed tool"):
        opencode_effective_inventory(config, allow_task, tools, profile=profile)
    with pytest.raises(NativeInventoryRejected, match="deny-all"):
        opencode_effective_inventory(
            {**config, "permission": {"*": "allow", "task": "allow"}},
            agents, tools, profile=profile,
        )
    with pytest.raises(NativeInventoryRejected, match="malformed"):
        opencode_effective_inventory(config, agents, ["task", "task"], profile=profile)


def test_host_request_schemas_have_no_agent_tool_or_enablement_surface():
    reject_host_enablement_request()


def test_codex_bootstrap_recorder_captures_actual_rpc_surfaces_without_turn(tmp_path):
    home = tmp_path / "codex-home"
    home.mkdir()
    (home / "config.toml").write_bytes(CODEX_CONFIG)
    database = tmp_path / "codex.sqlite"
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE driver_events(kind TEXT,body TEXT)")

    class Journal:
        def _connect(self):
            return sqlite3.connect(database)

    class Driver:
        profile = SimpleNamespace(
            version="0.153.2", codex_home=str(home),
            permission_profile="achp-engineer", cwd="/tmp/cwd",
            executable_sha256="a" * 64,
        )
        journal = Journal()
        session_id = None

        def _rpc(self, _operation, method, _params, **_kwargs):
            if method == "thread/start":
                return {"activePermissionProfile": {"id": "achp-engineer"},
                        "approvalPolicy": "never", "cwd": "/tmp/cwd"}
            if method == "experimentalFeature/list":
                return {"data": [{"name": "multi_agent", "enabled": False},
                                 {"name": "multi_agent_v2", "enabled": False}]}
            raise AssertionError("unexpected native RPC")

        def spawn(self, operation):
            self._rpc(operation, "thread/start", {"cwd": "/tmp/cwd"})
            self._rpc(operation, "experimentalFeature/list", {"threadId": "thread", "limit": 100})
            self.session_id = "session"

    summary = capture_codex_bootstrap(Driver(), object())
    assert summary["model_turn_count"] == 0
    assert summary["_witness"]["feature_reads"][0][1]["data"][0] == {
        "name": "multi_agent", "enabled": False,
    }


def test_opencode_bootstrap_recorder_captures_effective_agent_and_tools(tmp_path):
    database = tmp_path / "opencode.sqlite"
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE driver_events(kind TEXT,body TEXT)")

    class Journal:
        def _connect(self):
            return sqlite3.connect(database)

    class Driver:
        profile = SimpleNamespace(
            version="1.18.30", agent="observer",
            data_root=str(tmp_path / "data"), temp_root=str(tmp_path / "temp"),
            config_sha256="a" * 64, executable_sha256="b" * 64,
        )
        journal = Journal()
        session_id = None

        def _http(self, _operation, method, path, _payload=None, **_kwargs):
            assert method == "GET"
            values = {
                "/config": {
                    "permission": {"*": "deny", "task": "deny"},
                    "default_agent": "observer",
                    "agent": {"observer": {"permission": {"*": "deny", "task": "deny"}}},
                    "plugin": [], "mcp": {},
                },
                "/agent": [{"name": "observer", "permission": [
                    {"permission": "*", "pattern": "*", "action": "deny"},
                ]}],
                "/experimental/tool/ids": ["task", "read"],
            }
            return 200, values[path]

        def spawn(self, operation):
            for path in ("/config", "/agent", "/experimental/tool/ids"):
                self._http(operation, "GET", path)
            self.session_id = "ses_fixture"

    summary = capture_opencode_bootstrap(Driver(), object())
    assert summary["model_prompt_count"] == 0
    assert summary["effective_tool_count"] == 2
    assert summary["_witness"]["tool_ids"] == ["task", "read"]


def test_no_model_inventory_adapter_keeps_formal_scene_not_run():
    scenario = "P1-NATIVE-MULTIAGENT-OFF"
    assert scenario in probe.ScenarioCatalog.LINEAGE_BOUND
    status = probe.availability({}, "a" * 40)[scenario]
    assert status == {
        "available": False,
        "reason": "actual native delegation request behavior is NOT_RUN",
        "tests": probe.ScenarioCatalog.TESTS[scenario],
    }


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="O_NOFOLLOW Linux copy")
def test_pinned_native_copy_uses_private_mode_and_rejects_source_race(
    tmp_path, monkeypatch,
):
    private = tmp_path / "private"
    private.mkdir(mode=0o700)
    source = tmp_path / "source"
    source.write_bytes(b"pinned native bytes")
    expected = hashlib.sha256(source.read_bytes()).hexdigest()
    target = private / "native"
    pin = _copy_pinned(
        source, target, expected_sha256=expected,
        expected_size=len(source.read_bytes()),
    )
    assert pin["source_sha256"] == pin["private_sha256"] == expected
    assert target.stat().st_mode & 0o777 == 0o500
    assert target.read_bytes() == source.read_bytes()

    raced_target = private / "raced"
    source_inode = source.stat().st_ino
    original_read = os.read
    changed = False

    def raced_read(descriptor, count):
        nonlocal changed
        data = original_read(descriptor, count)
        if data and not changed and os.fstat(descriptor).st_ino == source_inode:
            changed = True
            source.write_bytes(b"changed native bytes"[:len(b"pinned native bytes")])
        return data

    monkeypatch.setattr(os, "read", raced_read)
    with pytest.raises(NativeInventoryRejected, match="changed during copy"):
        _copy_pinned(
            source, raced_target, expected_sha256=expected,
            expected_size=len(b"pinned native bytes"),
        )
    assert changed and not raced_target.exists()


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="O_NOFOLLOW Linux copy")
def test_pinned_native_copy_rejects_atomic_path_replacement_after_open(
    tmp_path, monkeypatch,
):
    private = tmp_path / "private"
    private.mkdir(mode=0o700)
    source = tmp_path / "source"
    source.write_bytes(b"pinned native bytes")
    expected = hashlib.sha256(source.read_bytes()).hexdigest()
    target = private / "replaced"
    original_open = os.open
    swapped = False

    def open_then_replace(path, flags, mode=0o777, *, dir_fd=None):
        nonlocal swapped
        descriptor = original_open(path, flags, mode, dir_fd=dir_fd)
        if path == source and not swapped:
            swapped = True
            replacement = tmp_path / "replacement"
            replacement.write_bytes(b"changed native bytes")
            os.replace(replacement, source)
        return descriptor

    monkeypatch.setattr(os, "open", open_then_replace)
    with pytest.raises(NativeInventoryRejected, match="changed (?:during copy|path)"):
        _copy_pinned(
            source, target, expected_sha256=expected,
            expected_size=len(b"pinned native bytes"),
        )
    assert swapped and not target.exists()
