"""Existing signed readback transports exact original Native provenance only."""
from __future__ import annotations

import sqlite3

import pytest

from runtime.communication_client_native_source import _original_selection
from runtime.native_view_models import ProviderAdmission
from runtime.receiver import ReceiverRejected
from runtime.receiver_models import NativeSourceReadbackBody
from runtime_tests.test_receiver_evidence_native import receiver as receiver_fixture
from runtime_tests.test_signed_harness_adapter import (
    prepare_command,
    run,
)
from runtime_tests.test_signed_harness_adapter import signed as signed_fixture

receiver = receiver_fixture
signed = signed_fixture


def completed(signed):
    command = prepare_command(signed)
    assert run(signed.facade.admit_input(command)).outcome == "accepted"
    provider = ProviderAdmission(provider_ref="trusted-remote-original", native_authority="harness",
        selection=_original_selection(signed.invocation))
    body = NativeSourceReadbackBody(operation_id=signed.invocation.operation_id, dispatch_id=signed.invocation.dispatch_id,
        native_source=True, provider_admission=provider.model_dump(mode="json"))
    return signed.factory.request("delivery.readback", body)


def test_source_readback_uses_original_driver_journal_and_never_calls_native(signed):
    request = completed(signed)
    with signed.driver.journal._connect() as connection:
        before = connection.execute("SELECT count(*) FROM driver_events").fetchone()
    observed = []

    def reader(admission, provider):
        # The callback may use its own journal/Core readers without a Receiver
        # SQL lock or transaction spanning that work.
        with sqlite3.connect(signed.service.config.ledger_path, timeout=0.1) as connection:
            connection.execute("BEGIN IMMEDIATE")
        value = signed.bridge.read_native_source(admission, provider)
        observed.append(True)
        return value

    result = signed.service.readback(request, native_source_reader=reader)
    value = result.receipt.evidence["native_source"]
    assert value["available"] is True
    assert value["value"]["operationId"] == signed.invocation.operation_id
    assert value["value"]["messageHandle"] == "message:fixture-project:fixture-message"
    assert value["value"]["nativeSession"]["providerRef"] == "trusted-remote-original"
    assert value["evidence_ref"].startswith("driver-source:")
    assert signed.service.readback(request, native_source_reader=reader) == result
    assert observed == [True]
    with signed.driver.journal._connect() as connection:
        assert connection.execute("SELECT count(*) FROM driver_events").fetchone() == before


def test_source_readback_reauthorizes_cached_and_inflight_results(signed):
    request = completed(signed)
    result = signed.service.readback(request, native_source_reader=signed.bridge.read_native_source)
    assert result.receipt.evidence["native_source"]["available"]
    signed.state.authorized = False
    with pytest.raises(ReceiverRejected, match="authority"):
        signed.service.readback(request, native_source_reader=signed.bridge.read_native_source)
    signed.state.authorized = True
    next_request = completed_read(signed)

    def revoke(admission, provider):
        value = signed.bridge.read_native_source(admission, provider)
        signed.state.authorized = False
        return value

    with pytest.raises(ReceiverRejected, match="authority"):
        signed.service.readback(next_request, native_source_reader=revoke)


def completed_read(signed):
    provider = ProviderAdmission(provider_ref="trusted-remote-original", native_authority="harness",
        selection=_original_selection(signed.invocation))
    return signed.factory.request("delivery.readback", NativeSourceReadbackBody(operation_id=signed.invocation.operation_id,
        dispatch_id=signed.invocation.dispatch_id, native_source=True, provider_admission=provider.model_dump(mode="json")))


def test_source_body_rejects_paths_or_wrong_original_receiving_scope(signed):
    request = completed(signed)
    body = request.body | {"path": "/private/other-session.sqlite"}
    forged = signed.factory.request("delivery.readback", body)
    with pytest.raises(ValueError):
        signed.service.readback(forged, native_source_reader=signed.bridge.read_native_source)
    wrong = request.body["provider_admission"] | {"provider_ref": "ignored-selector"}
    wrong["selection"] = wrong["selection"] | {"scope_id": "foreign-scope"}
    changed = signed.factory.request("delivery.readback", request.body | {"provider_admission": wrong})
    with pytest.raises(RuntimeError, match="scope"):
        signed.service.readback(changed, native_source_reader=signed.bridge.read_native_source)
