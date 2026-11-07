"""Real Driver transport paths over persistent controlled RPC/HTTP peers.

Session state and OS containment observations are explicitly test doubles. The
transport and Driver journals are real; no installed Native binary or model runs.
"""
from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
from dataclasses import asdict
from http.client import RemoteDisconnected
from types import SimpleNamespace

import pytest

from runtime.codex_driver import DriverRejected, OutcomeUncertain
from runtime.codex_jsonrpc import RpcTimeout
from runtime.native_restore import stopped_process
from runtime.receiver_contract import native_generation
from runtime.receiver_lifecycle import AuthorizedLifecycleOperation, lifecycle_operation_id
from runtime.supervisor import OwnedProcess
from runtime_tests import test_codex_driver as codex
from runtime_tests import test_opencode_driver as opencode


def operation(driver, source, action, *, restore=None):
    selected = getattr(driver, "thread_id", None) or driver.session_id if action == "resume" else None
    return AuthorizedLifecycleOperation(lifecycle_operation_id(source, action, restore_process_ref=restore),
        "command-" + source, source, "trusted-fixture-grant", None, action, driver.binding_id, driver.identity,
        selected, native_generation(driver.binding_id, asdict(driver.identity), selected) if selected else None, restore)


@pytest.fixture(params=("codex", "opencode"))
def transport(request, tmp_path, monkeypatch):
    module = codex if request.param == "codex" else opencode
    profile = module.profile.__wrapped__(tmp_path)
    args = (tmp_path, profile, monkeypatch) if module is codex else (tmp_path, profile)
    with contextmanager(module.native.__wrapped__)(*args) as state:
        old = state.driver
        old.detach_transport()  # Explicit operator adoption before any launch.
        old.journal.adopt_lifecycle_schema()
        peers, launches = [], []
        supervisor = old.supervisor

        class SupervisedTransport:
            def launch(self, argv, **options):
                if options.get("before_start"):
                    options["before_start"]()
                launches.append(argv)
                if module is codex:
                    peer = state.peer if not peers else codex.WirePeer(state.peer.handler)
                    peers.append(peer)
                    return OwnedProcess(peer, "controlled-job-" + str(len(launches)), "controlled-birth-" + str(len(launches)))
                previous = state.peer
                owned = supervisor.launch(argv, **options)
                if previous is not None:
                    state.peer.session = deepcopy(previous.session)
                    state.peer.sessions = deepcopy(previous.sessions)
                    state.peer.session_messages = deepcopy(previous.session_messages)
                    state.peer.messages = deepcopy(previous.messages)
                peers.append(state.peer)
                owned.birth_ref = "controlled-birth-" + str(len(launches))
                owned.containment_id = "controlled-job-" + str(len(launches))
                return owned

            def inspect(self, owned):
                if module is codex:
                    return {"verified": True, "birth_ref": owned.birth_ref, "containment_id": owned.containment_id,
                        "root_exited": owned.process.closed, "remaining_pids": [] if owned.process.closed else [owned.process.pid]}
                return supervisor.inspect(owned)

            def terminate_tree(self, owned):
                if module is codex:
                    owned.process.close()
                    return self.inspect(owned)
                return supervisor.terminate_tree(owned)

        driver = type(old)(old.binding_id, old.profile, old.journal, identity=old.identity,
            check_current=old.check_current, supervisor=SupervisedTransport(),
            **({"rpc_timeout": 0.2} if module is codex else {"readback_attempts": 1}))
        try:
            yield SimpleNamespace(driver=driver, module=module, state=state, peers=peers, launches=launches)
        finally:
            for peer in peers:
                peer.close()
            driver.detach_transport()


def test_original_session_restores_over_new_owned_transport_without_create_or_prompt(transport):
    f, driver = transport, transport.driver
    driver.spawn(operation(driver, "create", "spawn"))
    original = getattr(driver, "thread_id", None) or driver.session_id
    driver.supervisor.terminate_tree(driver.owned)
    reference = stopped_process(driver)["evidence_ref"]
    restore = operation(driver, "resume-original", "resume", restore=reference)
    result = driver.resume(restore)
    assert result["receipt_layer"] == "context_resumed"
    assert (getattr(driver, "thread_id", None) or driver.session_id) == original
    assert driver.resume(restore) == result and len(f.launches) == 2
    if f.module is codex:
        methods = [entry["method"] for peer in f.peers for entry in peer.requests]
        assert methods.count("thread/start") == 1 and methods.count("thread/resume") == 1
        assert "turn/start" not in methods
    else:
        requests = [entry for peer in f.peers for entry in peer.requests]
        assert sum(entry[0] == "POST" and entry[1] == "/session" for entry in requests) == 1
        assert not any(entry[0] == "POST" and "prompt" in entry[1] for entry in requests)


def test_stopped_transport_requires_restoration_capability_and_keeps_same_logical_context(transport):
    driver = transport.driver
    driver.spawn(operation(driver, "create", "spawn"))
    driver.supervisor.terminate_tree(driver.owned)
    with pytest.raises(DriverRejected, match="signed restoration identity"):
        driver.resume(operation(driver, "plain-resume", "resume"))
    assert len(transport.launches) == 1


@pytest.mark.parametrize("transport", ["opencode"], indirect=True)
def test_explicitly_replaced_session_restores_its_original_identity_instead_of_earlier_session(transport):
    driver = transport.driver
    driver.spawn(operation(driver, "create-before-replacement", "spawn"))
    previous = driver.session_id
    replacement = driver.replace_session(opencode.operation("explicitly-authorized-replacement"))
    original = replacement["native_session_id"]
    assert original != previous
    driver.supervisor.terminate_tree(driver.owned)
    restored = driver.resume(operation(driver, "restore-replacement", "resume", restore=stopped_process(driver)["evidence_ref"]))
    assert restored["native_session_id"] == original and driver.session_id == original
    requests = [entry for peer in transport.peers for entry in peer.requests]
    assert sum(entry[0] == "POST" and entry[1] == "/session" for entry in requests) == 2
    assert not any(entry[0] == "POST" and "prompt" in entry[1] for entry in requests)


def test_missing_original_creation_ack_never_creates_a_replacement(transport):
    driver = transport.driver
    created = operation(driver, "create", "spawn")
    driver.spawn(created)
    driver.supervisor.terminate_tree(driver.owned)
    reference = stopped_process(driver)["evidence_ref"]
    with driver.journal._connect() as connection:
        connection.execute("UPDATE driver_operations SET state='uncertain' WHERE operation_id=?", (created.operation_id,))
    with pytest.raises((DriverRejected, OutcomeUncertain)):
        driver.resume(operation(driver, "cannot-replace-unknown", "resume", restore=reference))
    assert len(transport.launches) == 1


def test_unknown_input_can_reconnect_only_its_original_domain_for_query_without_replay(transport):
    f, driver = transport, transport.driver
    driver.spawn(operation(driver, "create", "spawn"))
    incoming = f.module.operation("uncertain-original-input")
    if f.module is codex:
        f.state.state["drop_invoke_ack"] = True
    else:
        f.state.peer.drop_prompt_ack = True
    lost_ack = RpcTimeout if f.module is codex else (RemoteDisconnected, ConnectionResetError)
    with pytest.raises(lost_ack):
        driver.invoke(incoming, "Original authorized input; do not resend")
    assert driver.journal.read(incoming.operation_id)["state"] == "uncertain"
    driver.supervisor.terminate_tree(driver.owned)
    restore = operation(driver, "query-original-context", "resume", restore=stopped_process(driver)["evidence_ref"])
    assert driver.resume(restore)["receipt_layer"] == "context_resumed"
    assert driver.journal.read(incoming.operation_id)["state"] == "uncertain"
    with pytest.raises(OutcomeUncertain, match="unresolved operation"):
        driver.invoke(f.module.operation("new-input-cannot-bypass"), "Do not admit this")
    if f.module is codex:
        methods = [entry["method"] for peer in f.peers for entry in peer.requests]
        assert methods.count("turn/start") == 1
    else:
        requests = [entry for peer in f.peers for entry in peer.requests]
        assert sum(entry[0] == "POST" and "prompt" in entry[1] for entry in requests) == 1
    assert driver.reconcile(f.module.operation("read-original-ack"), incoming.operation_id)["receipt_layer"] == "runtime_acknowledged"
    assert driver.journal.read(incoming.operation_id)["state"] == "acknowledged"
