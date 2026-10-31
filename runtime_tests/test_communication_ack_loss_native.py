"""Real independent models with deliberately lost, already committed TLS ACKs."""
import os

import pytest

from runtime_tests.test_communication import comm as comm_fixture
from runtime_tests.test_communication_remote_native import (
    test_physical_signed_receiver_and_independent_reply as exercise_receiver,
)

comm = comm_fixture


@pytest.mark.skipif(os.getenv('ACS_REAL_ACK_LOSS_MODEL_TEST') != '1',
                    reason='independent real-model ACK-loss exercise is explicit opt-in')
def test_real_models_reply_while_dispatch_and_readback_acknowledgements_are_unknown(comm, tmp_path, monkeypatch):
    monkeypatch.setenv('ACS_TEST_NATIVE_ACK_LOSS', '1')
    monkeypatch.setenv('ACS_REAL_REMOTE_MODEL_TEST', '1')
    monkeypatch.delenv('ACS_INSTALLED_NATIVE_RECEIVER', raising=False)
    exercise_receiver(comm, tmp_path, monkeypatch, 'codex')
