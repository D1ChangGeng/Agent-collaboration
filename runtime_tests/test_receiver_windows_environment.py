"""Windows Native bootstrap must retain OS drive without broad inheritance."""
from pathlib import PureWindowsPath

import pytest

from runtime_deployment.receiver_codex import CodexReceiverRejected, _restricted_windows_environment


@pytest.mark.parametrize("system_root", [r"C:\Windows", r"X:\Windows"])
def test_restricted_receiver_has_mxc_host_drive_without_proxy_or_account_inheritance(monkeypatch, system_root):
    monkeypatch.setenv("SystemRoot", system_root)
    monkeypatch.setenv("SystemDrive", "Z:")
    for key in ("OPENAI_API_KEY", "HTTP_PROXY", "NODE_OPTIONS", "ACS_RECEIVER_DSN"):
        monkeypatch.setenv(key, "SECRET_MUST_NOT_BE_INHERITED")
    selected = _restricted_windows_environment({"executable": r"D:\native\bin\codex.exe", "codex_home": r"D:\owned\codex-home"})
    assert selected["SystemDrive"] == PureWindowsPath(system_root).drive
    assert selected["SystemRoot"] == system_root
    assert selected["PATH"] == "D:\\native\\bin;"+str(PureWindowsPath(system_root)/"System32")
    assert not {"OPENAI_API_KEY", "HTTP_PROXY", "NODE_OPTIONS", "ACS_RECEIVER_DSN"} & selected.keys()
    assert {selected[key] for key in ("HOME", "TMP", "TEMP")} == {r"D:\owned\home", r"D:\owned\tmp"}


@pytest.mark.parametrize("system_root", ["relative/Windows", r"\\server\share\Windows"])
def test_restricted_receiver_rejects_unreviewed_system_root(monkeypatch, system_root):
    monkeypatch.setenv("SystemRoot", system_root)
    with pytest.raises(CodexReceiverRejected, match="local absolute"):
        _restricted_windows_environment({"executable": r"D:\codex.exe", "codex_home": r"D:\owned\codex-home"})
