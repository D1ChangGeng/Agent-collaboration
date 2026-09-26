"""Actual loopback HTTP peer with separately committed message/part fixtures."""
from copy import deepcopy

import pytest

from runtime.codex_driver import DriverRejected, OutcomeUncertain
from runtime_tests.test_opencode_driver import native as native  # noqa: PLC0414
from runtime_tests.test_opencode_driver import operation, prompts
from runtime_tests.test_opencode_driver import profile as profile  # noqa: PLC0414


def staged_parts(native, monkeypatch, *, empty_reads=2, mutation=None, metadata=None):
    driver = native.driver
    original = driver._http
    reads = []
    parts = []

    def request(op, method, path, *args, **kwargs):
        result = original(op, method, path, *args, **kwargs)
        if method == "POST" and path.endswith("/prompt_async"):
            user = native.peer.messages[0]
            parts.extend(deepcopy(user["parts"]))
            if mutation == "wrong_text":
                parts[0]["text"] = "different authorized input"
            elif mutation == "duplicate":
                parts.append(deepcopy(parts[0]))
            elif mutation == "cross_part":
                parts[0]["messageID"] = "msg_other"
            user["parts"] = [] if empty_reads != 0 else deepcopy(parts)
            if metadata:
                user["info"].update(metadata)
        if method == "GET" and "/message/msg_" in path:
            reads.append(result[1])
            if empty_reads is not None and len(reads) == empty_reads:
                native.peer.messages[0]["parts"] = deepcopy(parts)
        return result

    monkeypatch.setattr(driver, "_http", request)
    return reads, parts


def test_message_header_precedes_parts_then_exact_response(native, monkeypatch):
    d = native.driver
    d.spawn(operation("spawn"))
    d.readback_attempts = 4
    reads, _ = staged_parts(native, monkeypatch)
    op = operation("invoke")
    receipt = d.invoke(op, "fixed prompt")
    assert [len(row["parts"]) for row in reads] == [0, 0, 1]
    assert receipt["receipt_layer"] == "runtime_acknowledged"
    assert d.invoke(op, "fixed prompt") == receipt
    native.peer.finish()
    terminal = d.collect_result(operation("collect"), op.operation_id)
    assert terminal["receipt_layer"] == "response_received"
    assert terminal["native_message_id"] == receipt["native_message_id"]
    assert len(prompts(native.peer)) == 1


def test_empty_parts_exhaust_bounded_window_and_never_resubmit(native, monkeypatch):
    d = native.driver
    d.spawn(operation("spawn"))
    d.readback_attempts = 3
    reads, parts = staged_parts(native, monkeypatch, empty_reads=None)
    op = operation("invoke")
    receipt = d.invoke(op, "fixed prompt")
    assert len(reads) == 3
    assert receipt["receipt_layer"] == "runtime_dispatched"
    assert d.journal.read(op.operation_id)["state"] == "uncertain"
    with pytest.raises(OutcomeUncertain):
        d.invoke(op, "fixed prompt")
    with pytest.raises(OutcomeUncertain, match="never resubmit"):
        d.reconcile(operation("still-pending"), op.operation_id)
    native.peer.messages[0]["parts"] = parts
    assert d.reconcile(operation("parts-committed"), op.operation_id)["receipt_layer"] == "runtime_acknowledged"
    assert len(prompts(native.peer)) == 1


@pytest.mark.parametrize("mutation", ["wrong_text", "duplicate", "cross_part"])
def test_nonempty_mismatch_after_pending_is_rejected(native, monkeypatch, mutation):
    d = native.driver
    d.spawn(operation("spawn"))
    d.readback_attempts = 8
    reads, _ = staged_parts(native, monkeypatch, mutation=mutation)
    op = operation("invoke")
    with pytest.raises(DriverRejected, match="exact authorized input"):
        d.invoke(op, "fixed prompt")
    assert len(reads) == 3
    assert d.journal.read(op.operation_id)["state"] == "uncertain"
    with pytest.raises(OutcomeUncertain):
        d.invoke(op, "fixed prompt")
    assert len(prompts(native.peer)) == 1


@pytest.mark.parametrize("metadata", [
    {"sessionID": "ses_other"}, {"role": "assistant"},
    {"agent": "other"}, {"model": {"providerID": "other", "modelID": "model"}},
    {"model": {"providerID": "provider", "modelID": "other"}},
    {"tools": {}}, {"system": "override"},
])
def test_incomplete_parts_never_hide_cross_binding(native, monkeypatch, metadata):
    d = native.driver
    d.spawn(operation("spawn"))
    d.readback_attempts = 5
    reads, _ = staged_parts(native, monkeypatch, empty_reads=None, metadata=metadata)
    with pytest.raises(DriverRejected, match="exact authorized input"):
        d.invoke(operation("invoke"), "fixed prompt")
    assert len(reads) == 1
    assert len(prompts(native.peer)) == 1


@pytest.mark.parametrize("route", ["inspect", "collect_result"])
@pytest.mark.parametrize("malformed", ["scalar", "none", "nested", "mixed", "string", "scalar_container", "none_container", "mapping_container"])
def test_malformed_parts_are_controlled_rejections(native, route, malformed):
    d = native.driver
    d.spawn(operation("spawn"))
    op = operation("invoke")
    receipt = d.invoke(op, "fixed prompt")
    good = deepcopy(native.peer.messages[0]["parts"][0])
    values = {
        "scalar": [42], "none": [None], "nested": [[good]], "mixed": [good, 42],
        "string": ["part"], "scalar_container": 42, "none_container": None,
        "mapping_container": good,
    }
    native.peer.messages[0]["parts"] = values[malformed]
    with pytest.raises(DriverRejected, match="parts are malformed"):
        if route == "inspect":
            d.inspect(operation("inspect"))
        else:
            d.collect_result(operation("collect"), op.operation_id)
    assert d.journal.read(op.operation_id)["result"] == receipt
    assert len(prompts(native.peer)) == 1
