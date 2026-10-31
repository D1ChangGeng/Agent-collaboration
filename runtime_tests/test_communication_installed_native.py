"""Actual installed Receiver console entry in isolated WSL; never a production switch."""

from __future__ import annotations

import os

import pytest

from runtime_tests.test_communication import comm as comm_fixture
from runtime_tests.test_communication_remote_native import (
    test_physical_signed_receiver_and_independent_reply as exercise_receiver,
)

comm = comm_fixture


@pytest.mark.skipif(
    not os.getenv("ACS_INSTALLED_RECEIVER_WSL"), reason="installed WSL Receiver is explicit opt-in"
)
@pytest.mark.parametrize("sender_mode", ["lifecycle", "codex"])
def test_installed_receiver_console_and_independent_reply(comm, tmp_path, monkeypatch, sender_mode):
    if sender_mode == "codex" and os.getenv("ACS_REAL_INSTALLED_MODEL_TEST") != "1":
        pytest.skip("two actual model requests need the approved isolated Provider")
    monkeypatch.setenv("ACS_NATIVE_LOCAL_WSL", os.environ["ACS_INSTALLED_RECEIVER_WSL"])
    monkeypatch.setenv("ACS_REAL_REMOTE_MODEL_TEST", "1" if sender_mode == "codex" else "0")
    exercise_receiver(comm, tmp_path, monkeypatch, sender_mode)
