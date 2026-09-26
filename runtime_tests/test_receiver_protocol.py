from __future__ import annotations

import json
import multiprocessing
import os
import queue
import socket
import sqlite3
import stat
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Event
from types import SimpleNamespace

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID
from nacl.signing import SigningKey
from pydantic import ValidationError

from runtime import receiver_paths
from runtime.receiver import ReceiverRejected, ReceiverService
from runtime.receiver_config import (
    BootstrapRejected,
    ConnectionTarget,
    EndpointBootstrap,
    NodeIdentity,
    ReceiverRuntimeConfig,
)
from runtime.receiver_crypto import (
    SignatureRejected,
    key_fingerprint,
    load_owner_signing_key,
    public_key,
    sha256,
    sign,
    tls_fingerprint,
    verify,
)
from runtime.receiver_models import (
    DispatchBody,
    EndpointRegistration,
    PrepareBody,
    ReadbackBody,
    ReceiverReceipt,
    RecoveryBody,
    SignedReceipt,
    SignedRequest,
)
from runtime.remote_endpoint import (
    RemoteNodeTransport,
    RemoteTransportRejected,
    fixture_authority_current,
    serve,
)
from runtime.sender import AdmissionFactory, DeliveryIdentity


def fixture_native_invoke(admission):
    return {"native_ack_ref": f"native-ack:{admission.dispatch_id}"}


@pytest.fixture(autouse=True)
def receiver_runtime_is_posix_only(request):
    if os.name != "posix" and request.node.name != "test_runtime_fails_closed_without_posix_paths":
        pytest.skip("receiver runtime revision 4 requires POSIX descriptor path admission")


def dispatch_process(config, node_seed, request, marker, release, results, calls, hold):
    try:
        svc = ReceiverService(
            config, SigningKey(node_seed), authorize_current=fixture_authority_current,
        )
        svc.claim_boot(config.expected_boot_incarnation, config.journal_generation,
                       old_boot_isolation_ref=config.old_boot_isolation_ref)

        def after_marker():
            marker.set()
            if hold:
                assert release.wait(10)

        def invoke(_admission):
            calls.put("invoke")
            return {"ack": "process"}

        receipt = svc.dispatch(request, invoke, after_marker=after_marker if hold else None)
        results.put(("ok", receipt.model_dump_json()))
    except BaseException as error:  # noqa: BLE001 - cross-process test reports exact failure
        results.put(("error", f"{type(error).__name__}:{error}"))


def certificate(tmp_path):
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "acs-receiver")])
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
            .serial_number(x509.random_serial_number()).not_valid_before(datetime.now(UTC)-timedelta(minutes=1))
            .not_valid_after(datetime.now(UTC)+timedelta(hours=1))
            .add_extension(x509.SubjectAlternativeName([x509.DNSName("localhost")]), critical=False)
            .sign(key, hashes.SHA256()))
    cert_path, key_path = tmp_path / "receiver-cert.pem", tmp_path / "receiver-key.pem"
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(key.private_bytes(serialization.Encoding.PEM,
                                           serialization.PrivateFormat.TraditionalOpenSSL,
                                           serialization.NoEncryption()))
    cert_path.chmod(0o600)
    key_path.chmod(0o600)
    return cert_path, key_path, tls_fingerprint(cert.public_bytes(serialization.Encoding.DER))


def free_port():
    with socket.socket() as source:
        source.bind(("127.0.0.1", 0))
        return source.getsockname()[1]


@pytest.fixture
def env(tmp_path):
    authority_key, node_key = SigningKey.generate(), SigningKey.generate()
    node_key_path = tmp_path / "node-signing.seed"
    node_key_path.write_text(node_key.encode().hex(), encoding="ascii")
    node_key_path.chmod(0o600)
    cert_path, tls_key_path, cert_hash = certificate(tmp_path)
    port = free_port()
    node = NodeIdentity(
        "tenant", "authority", "authority-incarnation", "node", 1, "runtime", 1,
        "machine", "boot-1", "scope", "slot", "node-key-1", public_key(node_key),
    )
    registration = EndpointRegistration(
        registration_id="registration-1", endpoint_id="endpoint", endpoint_revision=1,
        connection_ref="receiver-loopback", tenant_id=node.tenant_id,
        authority_id=node.authority_id, authority_incarnation=node.authority_incarnation,
        node_id=node.node_id, node_binding_revision=node.node_binding_revision,
        runtime_id=node.runtime_id, runtime_revision=node.runtime_revision,
        machine_id=node.machine_id, boot_incarnation=node.boot_incarnation,
        scope_id=node.scope_id, agent_slot_id=node.agent_slot_id,
        tls_certificate_sha256=cert_hash, config_sha256="c" * 64,
        expires_at=datetime.now(UTC)+timedelta(minutes=5),
    )
    bootstrap = EndpointBootstrap({"receiver-loopback": ConnectionTarget(
        "receiver-loopback", "127.0.0.1", port, "loopback")}, node)
    binding = bootstrap.register(registration, sign(node_key, registration))
    config = ReceiverRuntimeConfig(
        binding=binding, authority_key_id="authority-key-1", authority_key_revision=1,
        authority_public_key=public_key(authority_key),
        authority_public_key_fingerprint=key_fingerprint(public_key(authority_key)),
        tls_cert_path=str(cert_path), tls_key_path=str(tls_key_path),
        node_signing_key_path=str(node_key_path),
        ledger_path=str(tmp_path / "receiver.sqlite"),
        expected_boot_incarnation="boot-1", journal_generation=1,
    )
    prepare_body = PrepareBody(
        envelope={"message_id": "message", "command_id": "command", "operation_id": "operation"},
        invocation={"attempt_id": "attempt", "dispatch_id": "dispatch"},
        selection={"endpoint_id": "endpoint", "endpoint_revision": 1, "runtime_id": "runtime"},
    )
    identity = DeliveryIdentity(
        "message", "command", "operation", "attempt", "dispatch", 3,
        "a"*64, sha256(prepare_body.envelope), sha256(prepare_body.selection),
        sha256(prepare_body.invocation), datetime.now(UTC)+timedelta(minutes=5),
    )
    factory = AdmissionFactory(config, authority_key, identity)
    return SimpleNamespace(
        authority_key=authority_key, node_key=node_key, node=node, registration=registration,
        bootstrap=bootstrap, config=config, identity=identity, factory=factory,
        prepare_body=prepare_body, tmp_path=tmp_path,
    )


def service(env, authorize_current=fixture_authority_current):
    value = ReceiverService(env.config, env.node_key, authorize_current=authorize_current)
    value.claim_boot("boot-1", 1)
    return value


def test_runtime_fails_closed_without_posix_paths(env, monkeypatch):
    monkeypatch.setattr(receiver_paths, "PLATFORM", "nt")
    with pytest.raises(BootstrapRejected, match="POSIX-only"):
        env.config.validate()
    with pytest.raises(BootstrapRejected, match="POSIX-only"):
        ReceiverService(env.config, env.node_key, authorize_current=fixture_authority_current)
    with pytest.raises(BootstrapRejected, match="POSIX-only"):
        RemoteNodeTransport(env.config)


@pytest.mark.parametrize("field", ["node_signing_key_path", "tls_key_path"])
@pytest.mark.parametrize("mode", [0o400, 0o644])
def test_private_key_requires_exact_owner_mode_0600(env, field, mode):
    Path(getattr(env.config, field)).chmod(mode)
    with pytest.raises(BootstrapRejected, match="path identity"):
        env.config.validate()


@pytest.mark.parametrize("mode", [0o755, 0o777])
@pytest.mark.parametrize("target", ["key", "ledger"])
def test_receiver_rejects_nonprivate_final_parent(env, mode, target):
    parent = env.tmp_path / f"bad-{target}-{mode:o}"
    parent.mkdir(mode=0o700)
    parent.chmod(mode)
    if target == "key":
        path = parent / "node.seed"
        path.write_text(env.node_key.encode().hex(), encoding="ascii")
        path.chmod(0o600)
        config = replace(env.config, node_signing_key_path=str(path))
    else:
        config = replace(env.config, ledger_path=str(parent / "receiver.sqlite"))
    with pytest.raises(BootstrapRejected, match="path identity"):
        config.validate()


@pytest.mark.parametrize("target", ["key", "ledger"])
def test_receiver_rejects_parent_symlink(env, target):
    private = env.tmp_path / f"real-{target}"
    private.mkdir(mode=0o700)
    alias = env.tmp_path / f"alias-{target}"
    alias.symlink_to(private, target_is_directory=True)
    if target == "key":
        path = private / "node.seed"
        path.write_text(env.node_key.encode().hex(), encoding="ascii")
        path.chmod(0o600)
        config = replace(env.config, node_signing_key_path=str(alias / path.name))
    else:
        config = replace(env.config, ledger_path=str(alias / "receiver.sqlite"))
    with pytest.raises(BootstrapRejected, match="path identity"):
        config.validate()


def test_receiver_rejects_final_key_symlink(env):
    target = env.tmp_path / "alternate.seed"
    target.write_text(env.node_key.encode().hex(), encoding="ascii")
    target.chmod(0o600)
    alias = env.tmp_path / "node-link.seed"
    alias.symlink_to(target)
    config = replace(env.config, node_signing_key_path=str(alias))
    with pytest.raises(BootstrapRejected, match="path identity"):
        config.validate()
    with pytest.raises(SignatureRejected, match="open rejected"):
        load_owner_signing_key(alias)


def test_existing_ledger_requires_exact_owner_mode_0600(env):
    path = Path(env.config.ledger_path)
    path.write_bytes(b"")
    path.chmod(0o644)
    with pytest.raises(BootstrapRejected, match="path identity"):
        env.config.validate()
    with pytest.raises(BootstrapRejected, match="owner-only"):
        ReceiverService(env.config, env.node_key, authorize_current=fixture_authority_current)


def test_new_ledger_is_exclusively_created_0600_under_umask_022(env):
    previous = os.umask(0o022)
    try:
        svc = service(env)
    finally:
        os.umask(previous)
    assert stat.S_IMODE(Path(env.config.ledger_path).stat().st_mode) == 0o600
    assert svc.ledger._identity == receiver_paths.validated_file_identity(
        env.config.ledger_path, private=True,
    )


def test_ledger_replacement_after_open_is_rejected(env):
    svc = service(env)
    path = Path(env.config.ledger_path)
    original = svc.ledger._identity
    path.unlink()
    path.write_bytes(b"")
    path.chmod(0o600)
    assert receiver_paths.validated_file_identity(path, private=True) != original
    with pytest.raises(ReceiverRejected, match="identity changed"):
        svc.ledger.connect()


def test_ledger_replacement_during_sqlite_open_is_rejected(env, monkeypatch):
    svc = service(env)
    path = Path(env.config.ledger_path)
    real_connect = sqlite3.connect

    def replace_then_connect(*args, **kwargs):
        path.unlink()
        path.write_bytes(b"")
        path.chmod(0o600)
        return real_connect(*args, **kwargs)

    monkeypatch.setattr(sqlite3, "connect", replace_then_connect)
    with pytest.raises(ReceiverRejected, match="identity changed while opening"):
        svc.ledger.connect()


def prepare(env, svc, *, request_id=None, nonce=None):
    request = env.factory.request("delivery.prepare", env.prepare_body,
                                  request_id=request_id, nonce=nonce)
    return request, svc.prepare(request)


def dispatch_request(env, prepared, *, request_id=None, nonce=None):
    return env.factory.request(
        "delivery.dispatch",
        DispatchBody(prepare_request_id=prepared.admission.request_id,
                     marker_receipt_id="postgres-runtime-dispatched"),
        request_id=request_id, nonce=nonce,
    )


def resigned(env, request, **changes):
    admission = request.admission.model_copy(update=changes)
    return request.model_copy(update={
        "admission": admission, "signature": sign(env.authority_key, admission),
    })


def recovered_env(env, old_boot="boot-1", new_boot="boot-2", generation=2,
                  isolation_ref="proof"):
    node = replace(env.node, node_binding_revision=2, boot_incarnation=new_boot)
    registration = env.registration.model_copy(update={
        "registration_id": "registration-2", "endpoint_revision": 2,
        "node_binding_revision": 2, "boot_incarnation": new_boot,
    })
    bootstrap = EndpointBootstrap({"receiver-loopback": ConnectionTarget(
        "receiver-loopback", "127.0.0.1", env.config.binding.locator_port, "loopback")}, node)
    binding = bootstrap.register(registration, sign(env.node_key, registration))
    config = replace(
        env.config, binding=binding, expected_boot_incarnation=new_boot,
        journal_generation=generation, old_boot_isolation_ref=isolation_ref,
    )
    factory = AdmissionFactory(config, env.authority_key, env.identity)
    return SimpleNamespace(**{**vars(env), "node": node, "registration": registration,
                             "bootstrap": bootstrap, "config": config, "factory": factory,
                             "old_boot": old_boot, "new_boot": new_boot, "generation": generation})


def test_endpoint_registration_is_node_signed_and_locator_is_configuration_only(env):
    assert env.config.binding.locator_host == "127.0.0.1"
    assert "locator" not in env.registration.model_dump()
    with pytest.raises(ValidationError, match="Extra inputs"):
        EndpointRegistration.model_validate({**env.registration.model_dump(), "url": "https://attacker"})
    changed = env.registration.model_copy(update={"tls_certificate_sha256": "0" * 64})
    with pytest.raises(ValueError, match="signature rejected"):
        env.bootstrap.register(changed, sign(env.node_key, env.registration))
    unknown = env.registration.model_copy(update={"registration_id": "unknown", "connection_ref": "unknown"})
    with pytest.raises(BootstrapRejected, match="allowlisted"):
        env.bootstrap.register(unknown, sign(env.node_key, unknown))


def test_prepare_exact_replay_and_signature_body_nonce_mutations(env):
    svc = service(env)
    request, first = prepare(env, svc)
    assert svc.prepare(request) == first
    another_prepare = env.factory.request("delivery.prepare", env.prepare_body)
    with pytest.raises(ReceiverRejected, match="logical identity"):
        svc.prepare(another_prepare)
    verify(env.config.binding.node_public_key, first.signature, first.receipt)
    changed_body = request.model_copy(update={"body": {"envelope": {}, "invocation": {}, "selection": {}}})
    with pytest.raises(ReceiverRejected, match="context"):
        svc.prepare(changed_body)
    changed_signature = request.model_copy(update={"signature": "00" * 64})
    with pytest.raises(ValueError, match="signature rejected"):
        svc.prepare(changed_signature)
    second = env.factory.request("delivery.prepare", env.prepare_body, nonce=request.admission.nonce)
    with pytest.raises(ReceiverRejected, match="nonce"):
        svc.prepare(second)
    changed_attempt = request.model_copy(update={"admission": request.admission.model_copy(
        update={"request_id": "changed-request", "attempt_id": "other-attempt"})})
    changed_attempt = changed_attempt.model_copy(update={"signature": sign(env.authority_key,
                                                                           changed_attempt.admission)})
    with pytest.raises(ReceiverRejected, match="attempt"):
        svc.prepare(changed_attempt)


def test_dispatch_marker_crash_is_uncertain_and_never_reinvokes(env):
    svc = service(env)
    prepared, _ = prepare(env, svc)
    request = dispatch_request(env, prepared)
    calls = []

    class Crash(BaseException):
        pass

    with pytest.raises(Crash):
        svc.dispatch(request, lambda admission: calls.append(admission.dispatch_id),
                     after_marker=lambda: (_ for _ in ()).throw(Crash()))
    assert calls == []
    restarted = ReceiverService(env.config, env.node_key, authorize_current=fixture_authority_current)
    restarted.claim_boot("boot-1", 1)
    recovered = restarted.dispatch(request, lambda admission: calls.append(admission.dispatch_id))
    assert recovered.receipt.state == "uncertain" and calls == []
    with sqlite3.connect(env.config.ledger_path) as connection:
        assert connection.execute("SELECT local_dispatch_marker,state FROM receiver_requests "
                                  "WHERE request_id=?", (request.admission.request_id,)).fetchone() == (1, "uncertain")


def test_marker_then_current_authority_rejection_records_blocked_without_invoke(env):
    current = {"allowed": True}
    svc = service(env, lambda _: current["allowed"])
    prepared, _ = prepare(env, svc)
    request = dispatch_request(env, prepared)
    calls = []

    def revoke():
        current["allowed"] = False

    result = svc.dispatch(request, lambda _: calls.append("forbidden") or {}, after_marker=revoke)
    assert result.receipt.state == "blocked" and calls == []
    readback = svc.readback(env.factory.request(
        "delivery.readback", ReadbackBody(operation_id=env.identity.operation_id,
                                          dispatch_id=env.identity.dispatch_id),
    ))
    assert readback.receipt.evidence["stored_state"] == "blocked"


def test_marker_then_deadline_expiry_records_blocked_without_invoke(env):
    identity = replace(env.identity, deadline=datetime.now(UTC)+timedelta(milliseconds=500))
    factory = AdmissionFactory(env.config, env.authority_key, identity)
    svc = service(env)
    prepared = factory.request("delivery.prepare", env.prepare_body)
    svc.prepare(prepared)
    dispatch = factory.request("delivery.dispatch", DispatchBody(
        prepare_request_id=prepared.admission.request_id,
        marker_receipt_id="postgres-runtime-dispatched"))
    calls = []
    result = svc.dispatch(dispatch, lambda _: calls.append("forbidden") or {},
                          after_marker=lambda: time.sleep(0.55))
    assert result.receipt.state == "blocked" and calls == []


def test_marker_then_registration_expiry_records_blocked_without_invoke(env):
    registration = env.registration.model_copy(update={
        "expires_at": datetime.now(UTC)+timedelta(milliseconds=500),
    })
    binding = env.config.binding.model_copy(update={
        "registration": registration,
        "registration_signature": sign(env.node_key, registration),
    })
    config = replace(env.config, binding=binding, ledger_path=str(env.tmp_path / "expiring.sqlite"))
    factory = AdmissionFactory(config, env.authority_key, env.identity)
    svc = ReceiverService(config, env.node_key, authorize_current=fixture_authority_current)
    svc.claim_boot("boot-1", 1)
    prepared = factory.request("delivery.prepare", env.prepare_body)
    svc.prepare(prepared)
    dispatch = factory.request("delivery.dispatch", DispatchBody(
        prepare_request_id=prepared.admission.request_id,
        marker_receipt_id="postgres-runtime-dispatched"))
    calls = []
    result = svc.dispatch(dispatch, lambda _: calls.append("forbidden") or {},
                          after_marker=lambda: time.sleep(0.55))
    assert result.receipt.state == "blocked" and calls == []


def test_marker_then_boot_replacement_records_blocked_without_invoke(env):
    svc = service(env)
    prepared, _ = prepare(env, svc)
    request = dispatch_request(env, prepared)
    calls = []

    def replace_boot():
        svc.ledger.claim_boot("boot-2", 2, old_boot_isolation_ref="isolated")

    result = svc.dispatch(request, lambda _: calls.append("forbidden") or {},
                          after_marker=replace_boot)
    assert result.receipt.state == "blocked" and calls == []
    assert result.receipt.evidence["reason"] == "boot_or_journal_generation_changed"


def test_boot_replacement_waits_for_final_writer_fence_through_native_call(env):
    svc = service(env)
    prepared, _ = prepare(env, svc)
    request = dispatch_request(env, prepared)
    entered, release = Event(), Event()

    def invoke(_):
        entered.set()
        assert release.wait(5)
        return {"ack": "one"}

    with ThreadPoolExecutor(max_workers=2) as pool:
        dispatch = pool.submit(svc.dispatch, request, invoke)
        assert entered.wait(5)
        replacement = pool.submit(
            svc.ledger.claim_boot, "boot-2", 2, old_boot_isolation_ref="isolated",
        )
        time.sleep(0.2)
        assert not replacement.done()
        release.set()
        assert dispatch.result(timeout=5).receipt.state == "runtime_acknowledged"
        replacement.result(timeout=5)


def test_dispatch_exact_replay_returns_signed_ack_once(env):
    svc = service(env)
    prepared, _ = prepare(env, svc)
    request = dispatch_request(env, prepared)
    calls = []
    first = svc.dispatch(request, lambda admission: calls.append(admission.dispatch_id) or {"ack": "actual"})
    second = svc.dispatch(request, lambda admission: calls.append("repeat") or {})
    assert first == second and first.receipt.state == "runtime_acknowledged"
    assert calls == [env.identity.dispatch_id]


def test_concurrent_exact_replay_observes_pending_without_mutating_owner(env):
    svc = service(env)
    prepared, _ = prepare(env, svc)
    request = dispatch_request(env, prepared)
    marker, release = Event(), Event()
    calls = []

    def after_marker():
        marker.set()
        assert release.wait(5)

    with ThreadPoolExecutor(max_workers=2) as pool:
        owner = pool.submit(
            svc.dispatch, request,
            lambda admission: calls.append(admission.dispatch_id) or {"ack": "owner"},
            after_marker=after_marker,
        )
        assert marker.wait(5)
        replay = pool.submit(
            svc.dispatch, request,
            lambda _admission: calls.append("forbidden-replay") or {},
        ).result(timeout=5)
        assert replay.receipt.state == "runtime_dispatched"
        with sqlite3.connect(env.config.ledger_path) as connection:
            state, lease = connection.execute(
                "SELECT state,execution_lease_id FROM receiver_requests WHERE request_id=?",
                (request.admission.request_id,),
            ).fetchone()
        assert state == "runtime_dispatched" and lease
        release.set()
        final = owner.result(timeout=5)
    assert final.receipt.state == "runtime_acknowledged"
    assert calls == [env.identity.dispatch_id]
    assert svc.dispatch(request, lambda _admission: calls.append("late") or {}) == final


def test_cross_process_exact_replay_preserves_single_execution(env):
    svc = service(env)
    prepared, _ = prepare(env, svc)
    request = dispatch_request(env, prepared)
    context = multiprocessing.get_context("fork")
    marker, release = context.Event(), context.Event()
    owner_results, replay_results, calls = context.Queue(), context.Queue(), context.Queue()
    owner = context.Process(
        target=dispatch_process,
        args=(env.config, env.node_key.encode(), request, marker, release,
              owner_results, calls, True),
    )
    owner.start()
    assert marker.wait(10)
    replay = context.Process(
        target=dispatch_process,
        args=(env.config, env.node_key.encode(), request, marker, release,
              replay_results, calls, False),
    )
    replay.start()
    replay.join(10)
    assert replay.exitcode == 0
    replay_kind, replay_json = replay_results.get(timeout=2)
    assert replay_kind == "ok"
    assert SignedReceipt.model_validate_json(replay_json, strict=True).receipt.state == "runtime_dispatched"
    release.set()
    owner.join(10)
    assert owner.exitcode == 0
    owner_kind, owner_json = owner_results.get(timeout=2)
    assert owner_kind == "ok"
    final = SignedReceipt.model_validate_json(owner_json, strict=True)
    assert final.receipt.state == "runtime_acknowledged"
    assert calls.get(timeout=2) == "invoke"
    with pytest.raises(queue.Empty):
        calls.get(timeout=0.2)
    restarted = ReceiverService(
        env.config, env.node_key, authorize_current=fixture_authority_current,
    )
    restarted.claim_boot("boot-1", 1)
    assert restarted.dispatch(request, lambda _admission: {"forbidden": True}) == final


def test_changed_request_id_and_nonce_for_same_logical_dispatch_cannot_reinvoke(env):
    svc = service(env)
    prepared, _ = prepare(env, svc)
    body = DispatchBody(prepare_request_id=prepared.admission.request_id,
                        marker_receipt_id="postgres-runtime-dispatched")
    first = env.factory.request("delivery.dispatch", body, request_id="dispatch-request-1",
                                nonce="1" * 64)
    second = env.factory.request("delivery.dispatch", body, request_id="dispatch-request-2",
                                 nonce="2" * 64)
    calls = []
    result = svc.dispatch(first, lambda admission: calls.append(admission.request_id) or {"ack": "one"})
    assert result.receipt.state == "runtime_acknowledged"
    assert svc.dispatch(first, lambda admission: calls.append("exact-replay")) == result
    with pytest.raises(ReceiverRejected, match="logical identity"):
        svc.dispatch(second, lambda admission: calls.append(admission.request_id) or {"ack": "two"})
    assert calls == ["dispatch-request-1"]


@pytest.mark.parametrize("field,value", [
    ("tenant_id", "changed-tenant"), ("authority_id", "changed-authority"),
    ("authority_incarnation", "changed-incarnation"), ("message_id", "changed-message"),
    ("command_id", "changed-command"), ("operation_id", "changed-operation"),
    ("attempt_id", "changed-attempt"), ("dispatch_id", "changed-dispatch"),
    ("endpoint_id", "changed-endpoint"), ("endpoint_revision", 2),
    ("runtime_id", "changed-runtime"), ("runtime_revision", 2),
    ("node_id", "changed-node"), ("machine_id", "changed-machine"),
    ("boot_incarnation", "changed-boot"), ("scope_id", "changed-scope"),
    ("agent_slot_id", "changed-slot"), ("accepted_revision", 4),
    ("accepted_state_digest", "f" * 64), ("envelope_digest", "f" * 64),
    ("selection_digest", "f" * 64), ("invocation_digest", "f" * 64),
    ("journal_generation", 2),
])
def test_dispatch_rejects_each_resigned_prepare_identity_change_without_invoke(env, field, value):
    svc = service(env)
    prepared, _ = prepare(env, svc)
    request = resigned(env, dispatch_request(env, prepared), **{field: value})
    calls = []
    with pytest.raises(ReceiverRejected):
        svc.dispatch(request, lambda admission: calls.append(admission.request_id) or {})
    assert calls == []


def test_dispatch_rejects_changed_deadline_lineage_without_invoke(env):
    svc = service(env)
    prepared, _ = prepare(env, svc)
    request = resigned(
        env, dispatch_request(env, prepared),
        deadline=prepared.admission.deadline-timedelta(seconds=1),
    )
    calls = []
    with pytest.raises(ReceiverRejected, match="prepared"):
        svc.dispatch(request, lambda _: calls.append("forbidden") or {})
    assert calls == []


def test_prepare_recomputes_all_three_canonical_digests_and_persists_signed_request(env):
    svc = service(env)
    request = env.factory.request("delivery.prepare", env.prepare_body)
    for field in ("envelope_digest", "selection_digest", "invocation_digest"):
        changed = resigned(env, request, **{field: "f" * 64})
        with pytest.raises(ReceiverRejected, match="canonical"):
            svc.prepare(changed)
    receipt = svc.prepare(request)
    with sqlite3.connect(env.config.ledger_path) as connection:
        connection.row_factory = sqlite3.Row
        row = connection.execute("SELECT * FROM receiver_requests WHERE request_id=?",
                                 (request.admission.request_id,)).fetchone()
    assert json.loads(row["signed_request_json"]) == request.model_dump(mode="json")
    assert json.loads(row["admission_json"]) == request.admission.model_dump(mode="json")
    assert json.loads(row["body_json"]) == request.body
    assert row["authority_signature"] == request.signature
    assert row["admission_sha256"] == sha256(request.admission)
    assert row["signed_request_sha256"] == sha256(request)
    stored_request = SignedRequest.model_validate_json(row["signed_request_json"], strict=True)
    verify(env.config.authority_public_key, stored_request.signature, stored_request.admission)
    stored_receipt = SignedReceipt.model_validate_json(row["receipt_json"], strict=True)
    assert row["receipt_sha256"] == sha256(stored_receipt.receipt)
    assert row["signed_receipt_sha256"] == sha256(stored_receipt)
    assert json.loads(row["prepare_identity_json"])["selection_digest"] == request.admission.selection_digest
    verify(env.config.binding.node_public_key, receipt.signature, receipt.receipt)


def test_multiple_readback_requests_do_not_conflict_with_prepare_or_dispatch(env):
    svc = service(env)
    prepared, _ = prepare(env, svc)
    dispatch = dispatch_request(env, prepared)
    svc.dispatch(dispatch, lambda _: {"ack": "one"})
    body = ReadbackBody(operation_id=env.identity.operation_id, dispatch_id=env.identity.dispatch_id)
    first = svc.readback(env.factory.request("delivery.readback", body, request_id="readback-1"))
    second = svc.readback(env.factory.request("delivery.readback", body, request_id="readback-2"))
    assert first.receipt.state == second.receipt.state == "readback"
    assert first.receipt.readback_request_id == "readback-1"
    assert first.receipt.target_request_id == dispatch.admission.request_id


def test_readback_body_and_admission_must_match_stored_dispatch_identity(env):
    svc = service(env)
    prepared, _ = prepare(env, svc)
    dispatch = dispatch_request(env, prepared)
    svc.dispatch(dispatch, lambda _: {"ack": "one"})
    body = ReadbackBody(operation_id=env.identity.operation_id, dispatch_id=env.identity.dispatch_id)
    request = env.factory.request("delivery.readback", body)
    changed_body = {"operation_id": "other", "dispatch_id": env.identity.dispatch_id}
    admission = request.admission.model_copy(update={"body_sha256": sha256(changed_body)})
    mismatched_body = request.model_copy(update={
        "body": changed_body, "admission": admission,
        "signature": sign(env.authority_key, admission),
    })
    with pytest.raises(ReceiverRejected):
        svc.readback(mismatched_body)
    changed = resigned(env, request, message_id="other-message")
    with pytest.raises(ReceiverRejected, match="stored dispatch"):
        svc.readback(changed)


@pytest.mark.parametrize("field,value", [
    ("receipt_id", "wrong-receipt"), ("request_id", "wrong-request"),
    ("target_request_id", "wrong-target"), ("readback_request_id", "wrong-readback"),
    ("challenge_nonce", "f" * 64), ("purpose", "delivery.readback"),
    ("tenant_id", "wrong-tenant"), ("authority_id", "wrong-authority"),
    ("authority_incarnation", "wrong-incarnation"), ("message_id", "wrong-message"),
    ("command_id", "wrong-command"), ("operation_id", "wrong-operation"),
    ("attempt_id", "wrong-attempt"), ("dispatch_id", "wrong-dispatch"),
    ("endpoint_id", "wrong-endpoint"), ("endpoint_revision", 2),
    ("runtime_id", "wrong-runtime"), ("runtime_revision", 2),
    ("node_id", "wrong-node"), ("node_binding_revision", 2),
    ("machine_id", "wrong-machine"), ("boot_incarnation", "wrong-boot"),
    ("scope_id", "wrong-scope"), ("agent_slot_id", "wrong-slot"),
    ("accepted_revision", 4), ("accepted_state_digest", "f" * 64),
    ("envelope_digest", "f" * 64), ("selection_digest", "f" * 64),
    ("invocation_digest", "f" * 64), ("journal_generation", 2),
    ("request_sha256", "f" * 64), ("state", "uncertain"),
])
def test_remote_transport_rejects_each_resigned_receipt_identity_mutation(env, field, value):
    svc = service(env)
    request, receipt = prepare(env, svc)
    changed = ReceiverReceipt.model_validate(
        {**receipt.receipt.model_dump(), field: value},
    )
    resigned = SignedReceipt(receipt=changed, node_key_id=receipt.node_key_id,
                             signature=sign(env.node_key, changed))
    with pytest.raises(RemoteTransportRejected, match="identity"):
        RemoteNodeTransport(env.config).validate_receipt(request, resigned)


def test_remote_transport_rejects_resigned_node_key_id_and_observation_time(env):
    svc = service(env)
    request, receipt = prepare(env, svc)
    changed_key = receipt.model_copy(update={"node_key_id": "wrong-key"})
    with pytest.raises(RemoteTransportRejected):
        RemoteNodeTransport(env.config).validate_receipt(request, changed_key)
    changed_time = receipt.receipt.model_copy(update={
        "observed_at": request.admission.deadline + timedelta(minutes=1),
    })
    resigned = SignedReceipt(receipt=changed_time, node_key_id=receipt.node_key_id,
                             signature=sign(env.node_key, changed_time))
    with pytest.raises(RemoteTransportRejected, match="identity"):
        RemoteNodeTransport(env.config).validate_receipt(request, resigned)


def test_boot_recovery_positive_requires_isolation_fresh_registration_and_no_marker(env):
    old = service(env)
    prepared, _ = prepare(env, old)
    current = recovered_env(env, isolation_ref="supervisor-stop-proof")
    recovered = ReceiverService(current.config, env.node_key,
                                authorize_current=fixture_authority_current)
    recovered.claim_boot("boot-2", 2, old_boot_isolation_ref="supervisor-stop-proof")
    body = RecoveryBody(
        prepare_request_id=prepared.admission.request_id,
        marker_receipt_id="postgres-runtime-dispatched", old_boot_incarnation="boot-1",
        new_boot_incarnation="boot-2", journal_generation=2,
        old_boot_isolation_ref="supervisor-stop-proof",
        old_endpoint_revision=1, new_endpoint_revision=2,
        old_runtime_revision=1, new_runtime_revision=1,
    )
    request = current.factory.request("delivery.recover", body, boot_incarnation="boot-2",
                                      journal_generation=2)
    calls = []
    first = recovered.recover(request, lambda admission: calls.append(admission.dispatch_id) or {"ack": "recovered"})
    second = recovered.recover(request, lambda admission: calls.append("repeat") or {})
    assert first == second and first.receipt.state == "runtime_acknowledged"
    assert calls == [env.identity.dispatch_id]
    another = current.factory.request("delivery.recover", body, boot_incarnation="boot-2",
                                      journal_generation=2)
    with pytest.raises(ReceiverRejected, match="marked dispatch"):
        recovered.recover(another, lambda _: {"ack": "forbidden"})


def test_authority_key_rotation_rejects_old_new_requests_but_retains_historical_verification(env):
    old_request = env.factory.request("delivery.prepare", env.prepare_body)
    verify(public_key(env.authority_key), old_request.signature, old_request.admission)
    new_key = SigningKey.generate()
    config = replace(
        env.config, authority_key_id="authority-key-2", authority_key_revision=2,
        authority_public_key=public_key(new_key),
        authority_public_key_fingerprint=key_fingerprint(public_key(new_key)),
        ledger_path=str(env.tmp_path / "rotated.sqlite"),
    )
    rotated = ReceiverService(config, env.node_key, authorize_current=fixture_authority_current)
    rotated.claim_boot("boot-1", 1)
    with pytest.raises(ReceiverRejected, match="context"):
        rotated.prepare(old_request)
    current = AdmissionFactory(config, new_key, env.identity).request("delivery.prepare", env.prepare_body)
    assert rotated.prepare(current).receipt.state == "prepared"
    verify(public_key(env.authority_key), old_request.signature, old_request.admission)


def test_node_key_rotation_uses_current_key_and_preserves_old_receipt_verification(env):
    old = service(env)
    request, old_receipt = prepare(env, old)
    old_public = env.config.binding.node_public_key
    verify(old_public, old_receipt.signature, old_receipt.receipt)
    new_key = SigningKey.generate()
    new_key_path = env.tmp_path / "node-signing-2.seed"
    new_key_path.write_text(new_key.encode().hex(), encoding="ascii")
    new_key_path.chmod(0o600)
    node = replace(env.node, node_binding_revision=2, boot_incarnation="boot-2",
                   node_key_id="node-key-2", node_public_key=public_key(new_key))
    registration = env.registration.model_copy(update={
        "registration_id": "registration-node-key-2", "endpoint_revision": 2,
        "node_binding_revision": 2, "boot_incarnation": "boot-2",
    })
    bootstrap = EndpointBootstrap({"receiver-loopback": ConnectionTarget(
        "receiver-loopback", "127.0.0.1", env.config.binding.locator_port, "loopback")}, node)
    binding = bootstrap.register(registration, sign(new_key, registration))
    config = replace(env.config, binding=binding, node_signing_key_path=str(new_key_path),
                     ledger_path=str(env.tmp_path / "node-key-2.sqlite"),
                     expected_boot_incarnation="boot-2")
    with pytest.raises(ReceiverRejected, match="signing key"):
        ReceiverService(config, env.node_key, authorize_current=fixture_authority_current)
    current = ReceiverService(config, new_key, authorize_current=fixture_authority_current)
    current.claim_boot("boot-2", 1)
    factory = AdmissionFactory(config, env.authority_key, env.identity)
    receipt = current.prepare(factory.request("delivery.prepare", env.prepare_body,
                                              boot_incarnation="boot-2"))
    verify(public_key(new_key), receipt.signature, receipt.receipt)
    verify(old_public, old_receipt.signature, old_receipt.receipt)
    assert request.admission.request_id == old_receipt.receipt.request_id


def test_authority_private_key_requires_owner_only_reference(env, tmp_path):
    if os.name != "posix":
        pytest.skip("owner/mode key admission is a POSIX deployment check")
    path = tmp_path / "authority.seed"
    path.write_text(env.authority_key.encode().hex(), encoding="ascii")
    path.chmod(0o600)
    assert public_key(load_owner_signing_key(path)) == public_key(env.authority_key)
    factory = AdmissionFactory.from_key_reference(env.config, str(path), env.identity)
    assert factory.request("delivery.prepare", env.prepare_body).admission.authority_key_id == "authority-key-1"
    link = tmp_path / "authority-link.seed"
    link.symlink_to(path)
    with pytest.raises(SignatureRejected, match="open"):
        load_owner_signing_key(link)
    path.chmod(0o644)
    with pytest.raises(SignatureRejected, match="mode"):
        load_owner_signing_key(path)


def test_receiver_tls_and_node_private_key_references_are_owner_only(env):
    if os.name != "posix":
        pytest.skip("owner/mode key admission is a POSIX deployment check")
    key = Path(env.config.tls_key_path)
    key.chmod(0o644)
    try:
        with pytest.raises(BootstrapRejected, match="owner-only"):
            env.config.validate()
    finally:
        key.chmod(0o600)


@pytest.mark.parametrize("change,error", [
    ({"old_boot_isolation_ref": "wrong"}, "isolation"),
    ({"journal_generation": 3}, "generation"),
    ({"new_boot_incarnation": "boot-3"}, "isolation"),
])
def test_boot_recovery_rejects_wrong_isolation_generation_or_boot(env, change, error):
    old = service(env)
    prepared, _ = prepare(env, old)
    current = recovered_env(env)
    recovered = ReceiverService(current.config, env.node_key,
                                authorize_current=fixture_authority_current)
    recovered.claim_boot("boot-2", 2, old_boot_isolation_ref="proof")
    values = {
        "prepare_request_id": prepared.admission.request_id,
        "marker_receipt_id": "marker", "old_boot_incarnation": "boot-1",
        "new_boot_incarnation": "boot-2", "journal_generation": 2,
        "old_boot_isolation_ref": "proof",
        "old_endpoint_revision": 1, "new_endpoint_revision": 2,
        "old_runtime_revision": 1, "new_runtime_revision": 1,
    }
    body = RecoveryBody(**(values | change))
    request = current.factory.request("delivery.recover", body, boot_incarnation="boot-2",
                                      journal_generation=2)
    with pytest.raises(ReceiverRejected, match=error):
        recovered.recover(request, lambda _: {"ack": "forbidden"})


@pytest.mark.parametrize("field,value", [
    ("message_id", "changed-message"), ("command_id", "changed-command"),
    ("operation_id", "changed-operation"), ("attempt_id", "changed-attempt"),
    ("dispatch_id", "changed-dispatch"), ("endpoint_id", "changed-endpoint"),
    ("runtime_id", "changed-runtime"), ("node_id", "changed-node"),
    ("machine_id", "changed-machine"), ("scope_id", "changed-scope"),
    ("agent_slot_id", "changed-slot"), ("accepted_revision", 4),
    ("accepted_state_digest", "f" * 64), ("envelope_digest", "f" * 64),
    ("selection_digest", "f" * 64), ("invocation_digest", "f" * 64),
])
def test_boot_recovery_rejects_each_changed_prepare_identity_without_invoke(env, field, value):
    old = service(env)
    prepared, _ = prepare(env, old)
    current = recovered_env(env)
    recovered = ReceiverService(current.config, env.node_key,
                                authorize_current=fixture_authority_current)
    recovered.claim_boot("boot-2", 2, old_boot_isolation_ref="proof")
    body = RecoveryBody(
        prepare_request_id=prepared.admission.request_id, marker_receipt_id="marker",
        old_boot_incarnation="boot-1", new_boot_incarnation="boot-2",
        journal_generation=2, old_boot_isolation_ref="proof",
        old_endpoint_revision=1, new_endpoint_revision=2,
        old_runtime_revision=1, new_runtime_revision=1,
    )
    request = resigned(
        env, current.factory.request("delivery.recover", body, boot_incarnation="boot-2",
                                     journal_generation=2),
        **{field: value},
    )
    calls = []
    with pytest.raises(ReceiverRejected):
        recovered.recover(request, lambda _: calls.append("forbidden") or {})
    assert calls == []


def test_boot_recovery_forbids_reinvoke_after_old_local_marker(env):
    old = service(env)
    prepared, _ = prepare(env, old)
    dispatch = dispatch_request(env, prepared)

    class Crash(BaseException):
        pass

    with pytest.raises(Crash):
        old.dispatch(dispatch, lambda _: {"ack": "forbidden"},
                     after_marker=lambda: (_ for _ in ()).throw(Crash()))
    current = recovered_env(env)
    recovered = ReceiverService(current.config, env.node_key,
                                authorize_current=fixture_authority_current)
    recovered.claim_boot("boot-2", 2, old_boot_isolation_ref="proof")
    body = RecoveryBody(
        prepare_request_id=prepared.admission.request_id, marker_receipt_id="marker",
        old_boot_incarnation="boot-1", new_boot_incarnation="boot-2",
        journal_generation=2, old_boot_isolation_ref="proof",
        old_endpoint_revision=1, new_endpoint_revision=2,
        old_runtime_revision=1, new_runtime_revision=1,
    )
    request = current.factory.request("delivery.recover", body, boot_incarnation="boot-2",
                                      journal_generation=2)
    with pytest.raises(ReceiverRejected, match="marked dispatch"):
        recovered.recover(request, lambda _: {"ack": "forbidden"})


def test_server_startup_rejects_signed_registration_for_unpresented_certificate(env):
    if not sys.platform.startswith("linux"):
        pytest.skip("forked TLS receiver evidence is measured on Linux")
    registration = env.registration.model_copy(update={
        "registration_id": "wrong-certificate-registration",
        "tls_certificate_sha256": "0" * 64,
    })
    binding = env.config.binding.model_copy(update={
        "registration": registration,
        "registration_signature": sign(env.node_key, registration),
        "locator_port": free_port(),
    })
    config = replace(env.config, binding=binding,
                     ledger_path=str(env.tmp_path / "wrong-certificate.sqlite"))
    ready = multiprocessing.Event()
    process = multiprocessing.Process(
        target=serve, args=(config, ready, fixture_authority_current, fixture_native_invoke),
    )
    process.start()
    process.join(5)
    assert not ready.is_set() and not process.is_alive() and process.exitcode != 0


def test_server_generation_two_restart_recovers_unmarked_prepare_once(env):
    if not sys.platform.startswith("linux"):
        pytest.skip("forked TLS receiver evidence is measured on Linux")
    old = service(env)
    prepared, _ = prepare(env, old)
    current = recovered_env(env, isolation_ref="server-old-boot-stopped")
    binding = current.config.binding.model_copy(update={"locator_port": free_port()})
    config = replace(current.config, binding=binding)
    ready = multiprocessing.Event()
    process = multiprocessing.Process(
        target=serve, args=(config, ready, fixture_authority_current, fixture_native_invoke),
    )
    process.start()
    try:
        assert ready.wait(5) and process.is_alive()
        body = RecoveryBody(
            prepare_request_id=prepared.admission.request_id,
            marker_receipt_id="postgres-runtime-dispatched",
            old_boot_incarnation="boot-1", new_boot_incarnation="boot-2",
            journal_generation=2, old_boot_isolation_ref="server-old-boot-stopped",
            old_endpoint_revision=1, new_endpoint_revision=2,
            old_runtime_revision=1, new_runtime_revision=1,
        )
        request = AdmissionFactory(config, env.authority_key, env.identity).request(
            "delivery.recover", body, boot_incarnation="boot-2", journal_generation=2,
        )
        first = RemoteNodeTransport(config).send(request)
        second = RemoteNodeTransport(config).send(request)
        assert first == second and first.receipt.state == "runtime_acknowledged"
        with sqlite3.connect(config.ledger_path) as connection:
            assert connection.execute("SELECT count(*) FROM native_calls").fetchone() == (1,)
    finally:
        process.terminate()
        process.join(5)
    assert not process.is_alive()


def test_server_rejects_nonmonotonic_generation_restart(env):
    if not sys.platform.startswith("linux"):
        pytest.skip("forked TLS receiver evidence is measured on Linux")
    service(env)
    current = recovered_env(env, generation=3, isolation_ref="server-old-boot-stopped")
    binding = current.config.binding.model_copy(update={"locator_port": free_port()})
    config = replace(current.config, binding=binding)
    ready = multiprocessing.Event()
    process = multiprocessing.Process(
        target=serve, args=(config, ready, fixture_authority_current, fixture_native_invoke),
    )
    process.start()
    process.join(5)
    assert not ready.is_set() and not process.is_alive() and process.exitcode != 0


def test_actual_tls13_two_process_signed_delivery_and_readback(env):
    if not sys.platform.startswith("linux"):
        pytest.skip("forked TLS receiver evidence is measured on Linux")
    ready = multiprocessing.Event()
    process = multiprocessing.Process(
        target=serve, args=(env.config, ready, fixture_authority_current, fixture_native_invoke),
    )
    process.start()
    evidence = {
        "schema_version": "acs-receiver-transport-evidence/1",
        "core_pid": os.getpid(), "receiver_pid": process.pid, "separate_process": process.pid != os.getpid(),
        "registration_id": env.registration.registration_id,
        "connection_ref": env.registration.connection_ref,
        "tls_certificate_sha256": env.registration.tls_certificate_sha256,
        "authority_public_key_fingerprint": env.config.authority_public_key_fingerprint,
        "node_public_key_fingerprint": key_fingerprint(env.config.binding.node_public_key),
        "model_invoked": False,
    }
    try:
        assert ready.wait(5) and process.is_alive()
        transport = RemoteNodeTransport(env.config)
        prepared = env.factory.request("delivery.prepare", env.prepare_body)
        prepare_receipt = transport.send(prepared)
        assert prepare_receipt.receipt.state == "prepared"
        evidence["prepare"] = prepare_receipt.model_dump(mode="json")
        dispatch = dispatch_request(env, prepared)
        first = transport.send(dispatch)
        second = transport.send(dispatch)
        assert first == second and first.receipt.state == "runtime_acknowledged"
        evidence["dispatch"] = first.model_dump(mode="json")
        evidence["exact_dispatch_replay"] = second == first
        readback = env.factory.request("delivery.readback", ReadbackBody(
            operation_id=env.identity.operation_id, dispatch_id=env.identity.dispatch_id))
        observed = transport.send(readback)
        assert observed.receipt.state == "readback"
        assert observed.receipt.evidence["stored_state"] == "runtime_acknowledged"
        evidence["readback"] = observed.model_dump(mode="json")
        with sqlite3.connect(env.config.ledger_path) as connection:
            assert connection.execute("SELECT count(*) FROM native_calls").fetchone() == (1,)
            evidence["native_call_count"] = 1
            evidence["ledger"] = connection.execute(
                "SELECT purpose,state,local_dispatch_marker,operation_id,attempt_id,dispatch_id "
                "FROM receiver_requests ORDER BY created_at",
            ).fetchall()
        with socket.create_connection((env.config.binding.locator_host, env.config.binding.locator_port)) as raw:
            context = RemoteNodeTransport._context()
            with context.wrap_socket(raw, server_hostname="localhost") as tls:
                assert tls.version() == "TLSv1.3"
                evidence["tls_version"] = tls.version()
        tampered = prepared.model_copy(update={"signature": "00" * 64})
        with pytest.raises(RemoteTransportRejected, match="status 409"):
            transport.send(tampered)
        wrong_registration = env.registration.model_copy(update={"tls_certificate_sha256": "0" * 64})
        wrong_binding = env.config.binding.model_copy(update={
            "registration": wrong_registration,
            "registration_signature": sign(env.node_key, wrong_registration),
        })
        wrong_config = replace(env.config, binding=wrong_binding)
        with pytest.raises(RemoteTransportRejected, match="fingerprint"):
            RemoteNodeTransport(wrong_config).send(env.factory.request("delivery.readback", ReadbackBody(
                operation_id=env.identity.operation_id, dispatch_id=env.identity.dispatch_id)))
        evidence["mutated_signature_rejected"] = True
        evidence["wrong_tls_fingerprint_rejected"] = True
        evidence["result"] = "pass"
    finally:
        process.terminate()
        process.join(5)
        evidence["receiver_process_exited"] = not process.is_alive()
    assert not process.is_alive()
    evidence_path = os.getenv("ACS_RECEIVER_EVIDENCE")
    if evidence_path:
        Path(evidence_path).write_text(json.dumps(evidence, sort_keys=True, default=list), encoding="utf-8")
