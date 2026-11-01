"""One-use challenge freshness and registered resource lifetime are separate."""
import json
from datetime import UTC, datetime, timedelta

import pytest
from nacl.signing import SigningKey

from runtime.errors import AcceptanceGuardFailed, AuthorizationDenied
from runtime.receiver_crypto import sign
from runtime.receiver_domain import ConnectionReferenceRegistration, EndpointRegistrationCommand
from runtime_tests.test_communication import comm as comm_fixture
from runtime_tests.test_receiver_domain_delivery import command, proof
from runtime_tests.test_receiver_opencode_factory import enrolled_opencode_config

comm = comm_fixture


def registration_request(comm, tmp_path, seconds):
    key = SigningKey.generate()
    config, _settings, observer = enrolled_opencode_config(comm, tmp_path, signing_key=key)
    with comm.authority._connect() as connection:
        for grant, permission in ((comm.authority.context.grant_ref, "receiver.manage"),
                                   (observer.context.grant_ref, "endpoint.register")):
            connection.execute("UPDATE grants SET permissions=permissions || %s::jsonb WHERE grant_ref=%s",
                (json.dumps([permission]), grant))
    comm.authority.register_receiver_connection(command(comm.authority, "receiver.connection.register", "connection", "test"),
        ConnectionReferenceRegistration(connection_ref="test", revision=1, locator_host="127.0.0.1", locator_port=12345,
            route_class="loopback", policy_digest="a" * 64, expires_at=datetime.now(UTC) + timedelta(minutes=10)))
    registration = config.binding.registration.model_copy(update={"connection_ref": "test",
        "expires_at": datetime.now(UTC) + timedelta(seconds=seconds)})
    envelope = command(observer, "endpoint.register", "endpoint", registration.endpoint_id)
    signature = sign(key, registration)
    node_input = {"registration": registration.model_dump(mode="json"), "registration_signature": signature}
    request = EndpointRegistrationCommand(registration=registration, registration_signature=signature,
        proof=proof(observer, key, "opencode-node", envelope, node_input))  # 120-second one-use challenge.
    return observer, envelope, request, registration


@pytest.mark.parametrize("seconds,accepted", [(180, True), (600, False)])
def test_shared_endpoint_is_bounded_by_runtime_and_grants_not_nonce(comm, tmp_path, seconds, accepted):
    observer, envelope, request, registration = registration_request(comm, tmp_path, seconds)
    if accepted:
        observer.register_receiver_endpoint(envelope, request)
        actual = observer.receiver_transport.load_endpoint(registration.endpoint_id)
        assert datetime.fromisoformat(actual["registration"]["expires_at"]) == registration.expires_at
    else:
        with pytest.raises(AcceptanceGuardFailed, match="Node/Runtime authority"):
            observer.register_receiver_endpoint(envelope, request)
        with comm.authority._connect() as connection:
            assert connection.execute("SELECT count(*) FROM delivery_endpoint_registrations").fetchone()[0] == 0


def test_nonce_expiry_during_registration_locks_still_rejects_commit(comm, tmp_path, monkeypatch):
    observer, envelope, request, _registration = registration_request(comm, tmp_path, 180)
    original = observer._authorize
    late = datetime.now(UTC) + timedelta(seconds=130)
    checks = 0
    def delayed(*args, **kwargs):
        nonlocal checks
        original(*args, **kwargs)
        if args[2] == "endpoint.register":
            checks += 1
            if checks == 2:
                monkeypatch.setattr(observer, "canonical_now", lambda cursor=None: late)
    monkeypatch.setattr(observer, "_authorize", delayed)
    with pytest.raises(AuthorizationDenied):
        observer.register_receiver_endpoint(envelope, request)
    assert checks == 2
    with comm.authority._connect() as connection:
        assert connection.execute("SELECT count(*) FROM delivery_endpoint_registrations").fetchone()[0] == 0
