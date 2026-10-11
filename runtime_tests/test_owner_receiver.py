"""Signed owner transport retains replay integrity across historical expiry."""
import sys
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from runtime.receiver import ReceiverRejected, ReceiverService
from runtime.receiver_crypto import sign
from runtime.receiver_models import DispatchBody, ReadbackBody
from runtime.sender import AdmissionFactory
from runtime_tests import test_receiver_protocol as reference

pytestmark = pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux private receiver paths")


@pytest.fixture
def owner_receiver(tmp_path):
    f = reference.env.__wrapped__(tmp_path)
    expired = f.registration.model_copy(update={"expires_at": datetime.now(UTC)-timedelta(days=1)})
    binding = f.config.binding.model_copy(update={"registration": expired,
        "registration_signature": sign(f.node_key, expired)})
    f.config = replace(f.config, binding=binding, access_mode="owner")
    f.identity = replace(f.identity, deadline=None)
    f.factory = AdmissionFactory(f.config, f.authority_key, f.identity)
    return f


def test_owner_signed_dispatch_unbounded_replay_and_forgery(owner_receiver):
    f = owner_receiver
    server = ReceiverService(f.config, f.node_key, authorize_current=lambda admission: True)
    server.claim_boot("boot-1", 1)
    prepared = f.factory.request("delivery.prepare", f.prepare_body)
    server.prepare(prepared)
    request = f.factory.request("delivery.dispatch", DispatchBody(
        prepare_request_id=prepared.admission.request_id, marker_receipt_id="marker"))
    calls = []
    def invoke(admission):
        calls.append(admission.dispatch_id)
        return {"native_ack_ref": "fixture-native"}
    assert server.dispatch(request, invoke).receipt.state == "runtime_acknowledged"
    assert server.dispatch(request, invoke).receipt.state == "runtime_acknowledged"
    assert calls == [f.identity.dispatch_id]
    forged = request.model_copy(update={"signature": "0"*128})
    with pytest.raises(ValueError):
        server.dispatch(forged, invoke)
    changed = request.model_copy(update={"body": {"prepare_request_id": prepared.admission.request_id,
                                                  "marker_receipt_id": "different-marker"}})
    with pytest.raises(ReceiverRejected):
        server.dispatch(changed, invoke)
    assert calls == [f.identity.dispatch_id]


def test_owner_readback_uses_its_own_request_after_task_expiry(owner_receiver):
    f = owner_receiver
    # Signed stored dispatch identity has a finite explicit business lifetime.
    identity = replace(f.identity, deadline=datetime.now(UTC)+timedelta(seconds=30))
    factory = AdmissionFactory(f.config, f.authority_key, identity)
    server = ReceiverService(f.config, f.node_key, authorize_current=lambda admission: True)
    server.claim_boot("boot-1", 1)
    prepared = factory.request("delivery.prepare", f.prepare_body)
    server.prepare(prepared)
    dispatch = factory.request("delivery.dispatch", DispatchBody(
        prepare_request_id=prepared.admission.request_id, marker_receipt_id="marker"))
    server.dispatch(dispatch, lambda admission: {"native_ack_ref": "fixture-native"})
    expired = replace(identity, deadline=datetime.now(UTC)-timedelta(days=1))
    reader = AdmissionFactory(f.config, f.authority_key, expired)
    read = reader.request("delivery.readback", ReadbackBody(operation_id=identity.operation_id,
                                                         dispatch_id=identity.dispatch_id))
    assert read.admission.deadline is None
    assert server.readback(read).receipt.evidence["stored_state"] == "runtime_acknowledged"
