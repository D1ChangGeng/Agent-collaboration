"""Probe approval/credential/cleanup boundaries without a real process."""
import json
from types import SimpleNamespace

import pytest

from tools.runtime import probe_codex_metadata as probe


def test_unapproved_probe_stops_before_reading_plan_or_creating_supervisor(monkeypatch):
    monkeypatch.delenv("ACS_EXECUTE_CODEX_METADATA_PROBE", raising=False)
    monkeypatch.setattr(probe, "checked", lambda *_args: pytest.fail("unapproved probe read a plan"))
    monkeypatch.setattr(probe, "WindowsJobSupervisor", lambda: pytest.fail("unapproved probe created a Job"))
    with pytest.raises(PermissionError):
        probe.execute("not-a-real-plan")


@pytest.mark.parametrize(("failure", "cleanup_failure"), [(False, False), (True, False), (False, True)])
def test_approved_metadata_calls_do_not_inherit_secrets_and_always_stop_owned_tree(tmp_path, monkeypatch, failure, cleanup_failure):
    monkeypatch.setenv("ACS_EXECUTE_CODEX_METADATA_PROBE", "approved")
    monkeypatch.setenv("SystemRoot", "C:/Windows")
    monkeypatch.setenv("OPENAI_API_KEY", "MUST_NOT_BE_INHERITED")
    monkeypatch.setenv("HTTP_PROXY", "MUST_NOT_BE_INHERITED")
    for name in ("home", "workspace", "temp", "appdata", "localappdata"):
        (tmp_path/name).mkdir()
    calls, lifecycle = [], []
    plan = {"root": str(tmp_path), "executable": "controlled-no-process.exe"}
    monkeypatch.setattr(probe, "checked", lambda _path: plan)
    owned = SimpleNamespace(process=SimpleNamespace(stdin=None,stdout=None,stderr=None))

    class Supervisor:
        def launch(self, argv, *, cwd, env, label, before_start):
            assert argv == [plan["executable"], "app-server"]
            assert cwd == str(tmp_path/"workspace") and label == "acs-metadata-probe"
            assert "OPENAI_API_KEY" not in env and "HTTP_PROXY" not in env
            assert env["CODEX_HOME"] == str(tmp_path/"home")
            assert env["ACS_METADATA_PROBE_TOKEN"] == "local-dummy-not-an-account"
            before_start(); lifecycle.append("launch")
            return owned

        def terminate_tree(self, actual):
            assert actual is owned
            lifecycle.append("terminate_owned")
            if cleanup_failure:
                raise RuntimeError("PRIVATE_TERMINATION_DETAIL")
            return {"verified": True, "root_exited": True, "remaining_pids": []}

        def close(self):
            lifecycle.append("close_job")

    class Client:
        def __init__(self, *_args, **_kwargs):
            pass

        def request(self, method, _params, *, timeout):
            assert method in probe.METHODS and timeout == 10
            calls.append(method)
            if failure:
                raise RuntimeError("PRIVATE_ACCOUNT_DETAIL_MUST_NOT_BE_IN_RESULT")
            return {"data": []}

        def notify(self, method, _params):
            assert method == "initialized"

        def close(self):
            lifecycle.append("close_transport")

    monkeypatch.setattr(probe, "WindowsJobSupervisor", Supervisor)
    monkeypatch.setattr(probe, "JsonRpcClient", Client)
    result = probe.execute(tmp_path/"plan.json")
    assert calls == (["initialize"] if failure else list(probe.METHODS))
    assert lifecycle == ["launch", "close_transport", "terminate_owned", "close_job"]
    assert result["Native_Sessions"] == result["model_prompts"] == 0
    assert result["owned_tree_stopped"] is (not cleanup_failure)
    assert result["status"] == ("metadata_failed" if failure else "metadata_complete")
    assert "PRIVATE_ACCOUNT" not in json.dumps(result)
    assert "PRIVATE_TERMINATION" not in json.dumps(result)
    if cleanup_failure:
        assert result["cleanup_error_type"] == "RuntimeError"
    assert (tmp_path/"result.json").is_file()


def test_metadata_allowlist_excludes_session_and_prompt_mutations():
    assert probe.METHODS == ("initialize", "experimentalFeature/list", "permissionProfile/list")
    assert "thread/start" not in probe.METHODS and "thread/resume" not in probe.METHODS and "turn/start" not in probe.METHODS
