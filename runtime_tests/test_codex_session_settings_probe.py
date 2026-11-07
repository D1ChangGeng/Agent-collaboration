"""Meaningful execution-boundary checks; every transport/process is controlled."""
import json
import tomllib
from pathlib import Path
from types import SimpleNamespace

import pytest

from tools.runtime import probe_codex_session_settings as probe


def test_metadata_approval_cannot_start_session_probe(monkeypatch):
    monkeypatch.delenv("ACS_EXECUTE_CODEX_EMPTY_SESSION_PROBE", raising=False)
    monkeypatch.setenv("ACS_EXECUTE_CODEX_METADATA_PROBE", "approved")
    monkeypatch.setattr(probe, "checked", lambda *_args: pytest.fail("read plan before separate approval"))
    monkeypatch.setattr(probe, "WindowsJobSupervisor", lambda: pytest.fail("created Job before separate approval"))
    with pytest.raises(PermissionError):
        probe.execute("absent.json")


def test_fixed_config_and_environment_exclude_execution_credentials_and_mcp(tmp_path, monkeypatch):
    monkeypatch.setenv("SystemRoot", "C:/Windows")
    monkeypatch.setenv("SystemDrive", "Z:")
    for name in ("OPENAI_API_KEY", "HTTP_PROXY", "NODE_OPTIONS", "CODEX_HOME"):
        monkeypatch.setenv(name, "DO_NOT_INHERIT")
    env = probe.environment(tmp_path)
    assert env["CODEX_HOME"] == str(tmp_path/"home")
    assert env["SystemDrive"] == "C:"
    assert not {"OPENAI_API_KEY", "HTTP_PROXY", "NODE_OPTIONS"} & env.keys()
    config = tomllib.loads(probe.configuration(tmp_path, Path("C:/codex.exe")))
    assert config["permissions"][probe.PROFILE]["network"] == {"enabled": False}
    assert set(config["permissions"][probe.PROFILE]["filesystem"].values()) == {"read"}
    assert config["features"] == dict.fromkeys(probe.DISABLED, False)
    assert config["windows"] == {"sandbox": "mxc"}
    assert config["project_root_markers"] == []
    assert "project_doc_max_bytes" not in config
    assert "mcp_servers" not in config and "sandbox_mode" not in config
    assert "turn/start" not in probe.METHODS and "thread/fork" not in probe.METHODS


def test_invalid_windows_system_root_cannot_fall_back_to_inherited_drive(tmp_path, monkeypatch):
    monkeypatch.setenv("SystemRoot", "relative/Windows")
    monkeypatch.setenv("SystemDrive", "C:")
    with pytest.raises(ValueError, match="local absolute"):
        probe.environment(tmp_path)


def test_feature_pagination_requires_positive_late_page_disablements():
    calls = []

    def request(method, params):
        calls.append((method, dict(params)))
        names = probe.DISABLED[:-1] if "cursor" not in params else probe.DISABLED[-1:]
        return {"data": [{"name": name, "enabled": False} for name in names],
                "nextCursor": "second-page" if "cursor" not in params else None}

    assert probe.features(request, "original-thread") == dict.fromkeys(probe.DISABLED, False)
    assert len(calls) == 2 and all(p["threadId"] == "original-thread" for _, p in calls)
    with pytest.raises(ValueError, match="positively observed"):
        probe.features(lambda *_: {"data": [], "nextCursor": None})
    with pytest.raises(ValueError, match="repeated"):
        probe.pages(lambda *_: {"data": [], "nextCursor": "same"}, "experimentalFeature/list", {})


@pytest.mark.parametrize("history_mode", ["legacy", "paginated"])
@pytest.mark.parametrize("failure", [None, "start_timeout", "start_rpc", "start_stop", "resume_identity", "resume_stop", "settings", "close_transport"])
def test_one_start_same_identity_resume_and_owned_cleanup(tmp_path, monkeypatch, failure, history_mode):
    monkeypatch.setenv("ACS_EXECUTE_CODEX_EMPTY_SESSION_PROBE", "approved")
    monkeypatch.setenv("SystemRoot", "C:/Windows")
    plan = {"root": str(tmp_path), "executable": "no-process.exe", "history_mode": history_mode}
    monkeypatch.setattr(probe, "checked", lambda *_args, **_kwargs: plan)
    calls, cleanup, launches = [], [], []
    clients = []

    class Supervisor:
        def __init__(self):
            self.number = len(launches)

        def launch(self, argv, *, cwd, env, label, before_start):
            assert argv == ["no-process.exe", "app-server"]
            assert cwd == str(tmp_path/"workspace") and env["CODEX_HOME"] == str(tmp_path/"home")
            before_start()
            self.owned = SimpleNamespace(process=SimpleNamespace(stdout=None, stdin=None, stderr=None))
            launches.append(self.owned)
            return self.owned

        def terminate_tree(self, owned):
            assert owned is self.owned
            cleanup.append((self.number, "terminate"))
            if failure == ("start_stop" if self.number == 0 else "resume_stop"):
                raise RuntimeError("PRIVATE_STOP_DETAIL")
            return {"verified": True, "root_exited": True, "remaining_pids": []}

        def close(self):
            cleanup.append((self.number, "close_job"))

    class Client:
        def __init__(self, *_args, **_kwargs):
            self.number = len(clients)
            clients.append(self)

        def request(self, method, params, *, timeout):
            assert 0 < timeout <= 10 and method in probe.METHODS
            calls.append((self.number, method, dict(params)))
            if method == "initialize":
                return {}
            if method == "experimentalFeature/list":
                return {"data": [{"name": name, "enabled": False} for name in probe.DISABLED]}
            if method == "permissionProfile/list":
                return {"data": [{"id": probe.PROFILE, "allowed": True}]}
            if method == "thread/turns/list":
                assert history_mode == "paginated"
                assert params == {"threadId": "one-thread", "itemsView": "full", "limit": 100, "sortDirection": "desc"}
                return {"data": [], "nextCursor": None}
            if method == "thread/start" and failure == "start_timeout":
                raise TimeoutError("PRIVATE_UNKNOWN_START")
            if method == "thread/start" and failure == "start_rpc":
                raise probe.RpcError({"code": -32000, "message": "PRIVATE_NATIVE_DETAIL"})
            thread = {"id": "one-thread", "sessionId": "one-session", "turns": []}
            if method == "thread/resume":
                assert params["threadId"] == "one-thread"
                assert params["excludeTurns"] is (history_mode == "paginated")
                assert cleanup[:2] == [(0, "terminate"), (0, "close_job")]
                if failure == "resume_identity":
                    thread["sessionId"] = "wrong-session"
            if method == "thread/read":
                assert params == {"threadId": "one-thread", "includeTurns": history_mode != "paginated"}
                return {"thread": thread}
            assert method in {"thread/start", "thread/resume"}
            if method == "thread/start":
                assert params.get("historyMode") == ("paginated" if history_mode == "paginated" else None)
            assert params["permissions"] == probe.PROFILE and "sandbox" not in params
            return {"thread": thread, "activePermissionProfile": {"id": probe.PROFILE},
                    "approvalPolicy": "never", "cwd": str(tmp_path/"workspace"),
                    "sandbox": {"type": "readOnly", "networkAccess": failure == "settings"},
                    "modelProvider": probe.PROVIDER, "model": probe.MODEL}

        def notify(self, method, params):
            assert method == "initialized" and params == {}

        def close(self):
            if failure == "close_transport":
                raise RuntimeError("PRIVATE_TRANSPORT_DETAIL")

    monkeypatch.setattr(probe, "WindowsJobSupervisor", Supervisor)
    monkeypatch.setattr(probe, "JsonRpcClient", Client)
    result = probe.execute(tmp_path/"plan.json")
    assert sum(m == "thread/start" for _, m, _ in calls) == result["session_start_requests"] == 1
    assert result["model_prompts"] == 0
    expected_launches = 1 if failure in {"start_timeout", "start_rpc", "start_stop", "settings"} else 2
    assert len(launches) == expected_launches
    assert cleanup == [(i, action) for i in range(expected_launches) for action in ("terminate", "close_job")]
    assert result["status"] == ("empty_session_probe_complete" if failure in {None, "close_transport"}
                                else "empty_session_probe_incomplete")
    if failure is None:
        assert result["phases"][0]["identity_sha256"] == result["phases"][1]["identity_sha256"]
        assert all(p["empty_history_readback"] and p["owned_tree_stopped"] for p in result["phases"])
        assert all(p.get("paginated_empty_history_readback", False) is (history_mode == "paginated") for p in result["phases"])
    if failure == "start_rpc":
        details = result["phases"][0]["rpc_failure"]
        assert details["code"] == -32000 and details["method"] == "thread/start"
        assert json.loads((tmp_path/details["private_artifact"]).read_text())["message"] == "PRIVATE_NATIVE_DETAIL"
    serialized = json.dumps(result)
    assert "PRIVATE_" not in serialized and "one-thread" not in serialized and "one-session" not in serialized
    assert (tmp_path/"result.json").is_file() and (tmp_path/"execution-started.json").is_file()
    # Even if a preceding run only dispatched a start, a second execution cannot launch.
    launches_before = len(launches)
    with pytest.raises(FileExistsError):
        probe.execute(tmp_path/"plan.json")
    assert len(launches) == launches_before
