"""Cold-resume probes require original identity/stop facts and cannot start."""
import hashlib
import json
from types import SimpleNamespace

import pytest

from tools.runtime import probe_codex_cold_resume as probe


def test_unapproved_cold_resume_cannot_read_plan_or_launch(monkeypatch):
    monkeypatch.delenv("ACS_EXECUTE_CODEX_EMPTY_SESSION_PROBE", raising=False)
    monkeypatch.setattr(probe, "checked", lambda *_: pytest.fail("unapproved read"))
    monkeypatch.setattr(probe, "WindowsJobSupervisor", lambda: pytest.fail("unapproved launch"))
    with pytest.raises(PermissionError):
        probe.execute("absent-plan.json")


@pytest.mark.parametrize("corruption", [None, "identity", "missing_identity", "history", "stop"])
def test_original_source_requires_real_identity_empty_history_and_stopped_tree(tmp_path, monkeypatch, corruption):
    common = probe.common
    monkeypatch.setattr(probe, "private_parent", lambda *_: None)
    for name in common.DIRECTORIES:
        (tmp_path/name).mkdir()
    executable, schema = tmp_path/"codex.exe", tmp_path/"schema.json"
    executable.write_bytes(b"controlled pinned executable")
    schema.write_bytes(b"controlled pinned schema")
    monkeypatch.setattr(common, "PINNED_EXE", common.digest(executable))
    monkeypatch.setattr(common, "PINNED_SCHEMA", common.digest(schema))
    config = tmp_path/"home/config.toml"
    config.write_text(common.configuration(tmp_path, executable), encoding="utf-8")
    plan = {"schema_version": "acs-codex-empty-session-probe/1", "root": str(tmp_path),
            "executable": str(executable), "schema": str(schema), "config_sha256": common.digest(config)}
    source_path = tmp_path/"plan.json"
    source_path.write_text(json.dumps(plan))
    selected = ("original-thread", "original-session")
    rollout = tmp_path/"home/sessions/owned.jsonl"
    rollout.parent.mkdir()
    record = {"type": "session_meta", "payload": {"id": selected[0], "session_id": selected[1]}}
    if corruption == "missing_identity":
        record["payload"].pop("session_id")
    rollout.write_text(json.dumps(record)+"\n")
    if corruption == "history":
        with rollout.open("a") as stream:
            stream.write(json.dumps({"type": "response_item", "payload": {"role": "user"}})+"\n")
    result = {"session_start_requests": 1, "model_prompts": 0, "phases": [{
        "methods": ["initialize", "thread/start"], "owned_tree_stopped": corruption != "stop",
        "identity_sha256": hashlib.sha256(json.dumps(selected).encode()).hexdigest() if corruption != "identity" else "wrong",
        "global_features": dict.fromkeys(common.DISABLED, False),
        "thread_features": dict.fromkeys(common.DISABLED, False),
        "settings": {"activePermissionProfile": {"id": common.PROFILE}, "approvalPolicy": "never",
                     "sandbox": {"type": "readOnly", "networkAccess": False},
                     "modelProvider": common.PROVIDER, "model": common.MODEL},
    }]}
    (tmp_path/"result.json").write_text(json.dumps(result))
    if corruption is not None:
        with pytest.raises(ValueError):
            probe.original(source_path)
    else:
        observed, actual, file = probe.original(source_path)
        assert observed == plan and actual == selected and file == rollout


@pytest.mark.parametrize("corruption", [None, "user_event", "other_thread", "write", "network", "approval", "extra_content"])
def test_settings_event_is_metadata_only_when_bound_and_restricted(tmp_path, corruption):
    common = probe.common
    metadata = {"type": "session_meta", "payload": {"id": "thread", "session_id": "session", "cwd": str(tmp_path)}}
    settings = {"active_permission_profile": {"id": common.PROFILE}, "approval_policy": "never",
                "model": common.MODEL, "model_provider_id": common.PROVIDER, "cwd": str(tmp_path),
                "permission_profile": {"type": "managed", "network": "restricted",
                    "file_system": {"type": "restricted", "entries": [{"access": "read"}]}}}
    event = {"type": "event_msg", "payload": {"type": "thread_settings_applied", "thread_id": "thread",
                                                 "thread_settings": settings}}
    if corruption == "user_event":
        event["payload"]["type"] = "user_message"
    elif corruption == "other_thread":
        event["payload"]["thread_id"] = "other"
    elif corruption == "write":
        settings["permission_profile"]["file_system"]["entries"][0]["access"] = "write"
    elif corruption == "network":
        settings["permission_profile"]["network"] = "enabled"
    elif corruption == "approval":
        settings["approval_policy"] = "on-request"
    elif corruption == "extra_content":
        event["payload"]["content"] = "hidden user message"
    rollout = tmp_path/"rollout.jsonl"
    rollout.write_text(json.dumps(metadata)+"\n"+json.dumps(event)+"\n")
    if corruption is None:
        assert probe.empty_rollout(rollout) == ("thread", "session")
    else:
        with pytest.raises(ValueError):
            probe.empty_rollout(rollout)


@pytest.mark.parametrize("failure", [None, "rpc", "identity", "stop"])
def test_only_exact_original_resume_metadata_read_and_owned_cleanup(tmp_path, monkeypatch, failure):
    monkeypatch.setenv("ACS_EXECUTE_CODEX_EMPTY_SESSION_PROBE", "approved")
    monkeypatch.setenv("SystemRoot", "C:/Windows")
    source_root = tmp_path/"original"
    source_root.mkdir()
    rollout = source_root/"owned.jsonl"
    selected = ("original-thread", "original-session")
    rollout.write_text(json.dumps({"type": "session_meta", "payload": {"id": selected[0], "session_id": selected[1]}})+"\n")
    plan = {"root": str(tmp_path), "original_identity_sha256": "controlled-hash"}
    source = {"root": str(source_root), "executable": "controlled-no-process.exe"}
    monkeypatch.setattr(probe, "checked", lambda *_: (plan, source, selected, rollout))
    calls, cleanup = [], []
    owned = SimpleNamespace(process=SimpleNamespace(stdin=None, stdout=None, stderr=None))

    class Supervisor:
        def launch(self, argv, *, cwd, env, label, before_start):
            assert argv == [source["executable"], "app-server"]
            assert cwd == str(source_root/"workspace") and env["SystemDrive"] == "C:"
            assert env["CODEX_HOME"] == str(source_root/"home")
            before_start()
            return owned

        def terminate_tree(self, actual):
            assert actual is owned
            cleanup.append("terminate")
            if failure == "stop":
                raise RuntimeError("PRIVATE_STOP")
            return {"verified": True, "root_exited": True, "remaining_pids": []}

        def close(self):
            cleanup.append("close_job")

    class Client:
        def __init__(self, *_args, **_kwargs):
            pass

        def request(self, method, params, *, timeout):
            assert method in probe.METHODS and method != "thread/start" and 0 < timeout <= 10
            calls.append((method, params))
            if method == "initialize":
                return {}
            if method == "experimentalFeature/list":
                return {"data": [{"name": name, "enabled": False} for name in probe.common.DISABLED]}
            if method == "permissionProfile/list":
                return {"data": [{"id": probe.common.PROFILE, "allowed": True}]}
            if method == "thread/resume":
                assert params["threadId"] == selected[0] and params["excludeTurns"] is True
                assert "history" not in params and "path" not in params
                if failure == "rpc":
                    raise probe.RpcError({"code": -32000, "message": "PRIVATE_RESUME_ERROR"})
            else:
                assert method == "thread/read" and params == {"threadId": selected[0], "includeTurns": False}
            response = {"thread": {"id": selected[0], "sessionId": selected[1], "turns": []},
                        "cwd": str(source_root/"workspace"), "activePermissionProfile": {"id": probe.common.PROFILE},
                        "approvalPolicy": "never", "sandbox": {"type": "readOnly", "networkAccess": False},
                        "modelProvider": probe.common.PROVIDER, "model": probe.common.MODEL}
            if failure == "identity":
                response["thread"]["sessionId"] = "another-session"
            return response

        def notify(self, method, params):
            assert method == "initialized" and params == {}

        def close(self):
            cleanup.append("close_transport")

    monkeypatch.setattr(probe, "WindowsJobSupervisor", Supervisor)
    monkeypatch.setattr(probe, "JsonRpcClient", Client)
    result = probe.execute(tmp_path/"plan.json")
    assert result["status"] == ("cold_resume_complete" if failure is None else "cold_resume_incomplete")
    assert result["new_Sessions"] == result["model_prompts"] == 0
    assert result["owned_tree_stopped"] is (failure != "stop")
    assert cleanup == ["close_transport", "terminate", "close_job"]
    assert sum(method == "thread/resume" for method, _ in calls) == 1
    assert all(method != "thread/start" for method, _ in calls)
    assert "PRIVATE_" not in json.dumps(result)
    if failure == "rpc":
        assert json.loads((tmp_path/"rpc-error.json").read_text())["message"] == "PRIVATE_RESUME_ERROR"
    count = len(calls)
    with pytest.raises(FileExistsError):
        probe.execute(tmp_path/"plan.json")
    assert len(calls) == count
