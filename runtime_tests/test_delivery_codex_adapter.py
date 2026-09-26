import pytest

from runtime_tests.native_delivery_checks import check_adapter
from runtime_tests.test_codex_driver import native as native  # noqa: PLC0414
from runtime_tests.test_codex_driver import operation
from runtime_tests.test_codex_driver import profile as profile  # noqa: PLC0414


@pytest.mark.parametrize("scenario", ["success", "idle_rejected", "authorization_rejected", "marker_rejected", "marker_failure", "ack_loss",
                                     "mutate_binding_id", "mutate_journal", "mutate_journal_path", "mutate_binding_identity",
                                     "mutate_claim_none", "mutate_claim_replaced", "mutate_claim_identity",
                                     "mutate_claim_same_path_reopen", "mutate_claim_released_owner", "mutate_claim_unlocked_owner"])
def test_codex_native_dispatch_boundary(native, tmp_path, monkeypatch, scenario):
    check_adapter(native, tmp_path, monkeypatch, scenario, operation)
