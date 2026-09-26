from __future__ import annotations

from types import SimpleNamespace

import pytest

from tools.runtime import p2_windows_receiver as receiver


def test_windows_provision_creates_receiver_ledger_parent_before_profile_use(
    tmp_path, monkeypatch,
):
    observed = []

    class StopProvision(Exception):
        pass

    monkeypatch.setattr(receiver, "_private", lambda path: observed.append(path))
    monkeypatch.setattr(
        receiver,
        "_json",
        lambda _path: (_ for _ in ()).throw(StopProvision()),
    )
    output = tmp_path / "receiver"
    with pytest.raises(StopProvision):
        receiver.provision(SimpleNamespace(output=output, profile=tmp_path / "profile.json"))
    assert observed == [output.resolve(), output.resolve() / "state"]
