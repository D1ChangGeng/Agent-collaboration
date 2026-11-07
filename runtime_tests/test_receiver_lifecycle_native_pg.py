"""Opt-in actual Core/TLS/Node/Windows Codex startup; no model or input turn.

Only the named local PG test container and a dummy loopback Provider are used.
Native protocol, process ownership, enrollment and original ACK recovery are real.
This qualifies neither independent model replies nor production cold recovery.
"""
from __future__ import annotations

import hashlib
import json
import os
import threading
import time
import traceback
from dataclasses import fields
from pathlib import Path

import pytest

from runtime.codex_driver import BindingIdentity, CodexAppServerDriver, DriverJournal, LaunchProfile
from runtime.connection_clock import ConnectionClock
from runtime.receiver_config import (
    ReceiverClientConfig,
    ReceiverRuntimeConfig,
    receiver_clock_identity,
)
from runtime.receiver_crypto import key_fingerprint
from runtime.receiver_lifecycle_capacity import (
    capture_capacity_profile,
    create_capacity_reservation,
)
from runtime.receiver_lifecycle_core import LifecycleCoreCallbacks
from runtime.receiver_lifecycle_node import ReceiverLifecycleNode
from runtime.receiver_lifecycle_transport import EXECUTE, RemoteLifecycleTransport
from runtime.remote_endpoint import ReceiverHTTPServer, RemoteNodeTransport
from runtime.supervisor import WindowsJobSupervisor
from runtime_tests.test_communication import comm as comm_fixture
from runtime_tests.test_receiver_lifecycle_issuance_pg import (
    PROJECT,
    RECEIVER,
    no_message_or_input,
    payload,
    setup_graph,
    snapshot,
    submit,
)
from runtime_tests.test_receiver_protocol import certificate, free_port
from tools.runtime import probe_codex_session_settings as pins

comm = comm_fixture


@pytest.mark.skipif(os.name != "nt" or os.getenv("ACS_REAL_NATIVE_LIFECYCLE_TEST") != "1",
                    reason="pinned Windows Native lifecycle acceptance is opt-in")
@pytest.mark.parametrize("lost_ack", [False, True])
def test_real_core_tls_prepares_one_actual_codex_session_and_reconciles_original_ack(comm, tmp_path, lost_ack):
    executable = Path(os.environ["ACS_NATIVE_LIFECYCLE_BINARY"]).resolve()
    schema = Path(os.environ["ACS_NATIVE_LIFECYCLE_SCHEMA"]).resolve()
    assert pins.digest(executable) == pins.PINNED_EXE and pins.digest(schema) == pins.PINNED_SCHEMA
    private = tmp_path/"native-private"
    pins.private_directory(private)
    for name in pins.DIRECTORIES:
        (private/name).mkdir()
    selected_config = private/"home/config.toml"
    selected_config.write_text(pins.configuration(private, executable), encoding="utf-8")
    cert, tls_key, fingerprint = certificate(private)
    f = setup_graph(comm, mode="owner", locator_port=free_port(), tls_certificate_sha256=fingerprint)
    original = submit(f)
    with f.authority._connect() as connection:
        selected = snapshot(f, connection)
    registration = selected.binding.registration
    identity = BindingIdentity(registration.node_id, registration.boot_incarnation, registration.runtime_id,
                               "actual-owned-codex-capacity", registration.agent_slot_id, registration.node_binding_revision)
    config = ReceiverClientConfig(selected.binding, selected.authority_key.key_id, selected.authority_key.revision,
        selected.authority_key.public_key, key_fingerprint(selected.authority_key.public_key), registration.boot_incarnation, 1)
    clock = ConnectionClock.local(f.authority.canonical_now, identity=receiver_clock_identity(config))
    binding_id = "native-owner-capacity-"+original["operation_id"]

    def authorize_namespace(namespace, current_binding_id, current_identity):
        assert namespace.parent == private and current_binding_id == binding_id and current_identity == identity
        # Real current source read and current registered endpoint are checked
        # during explicit Node provisioning, before any journal/process effect.
        f.recovery.read(PROJECT, original["operation_id"], f.secret)
        with f.authority._connect() as connection:
            assert snapshot(f, connection).binding == selected.binding

    reservation = create_capacity_reservation(private/"capacity", binding_id=binding_id, binding=identity,
                                               authorize_current_namespace=authorize_namespace)
    journal = DriverJournal(reservation.journal_path, clock=clock)
    journal.adopt_lifecycle_schema()
    profile = LaunchProfile(str(executable), pins.PINNED_EXE, "0.166.0", str(schema), pins.PINNED_SCHEMA,
        str(private/"workspace"), str(private/"home"), pins.digest(selected_config), pins.PROFILE,
        pins.environment(private), model=pins.MODEL, execution_mode="native", history_mode="paginated")
    supervisor = WindowsJobSupervisor()
    driver = CodexAppServerDriver(binding_id, profile, journal, identity=identity,
        check_current=lambda *_args: pytest.fail("Native access must use installed lifecycle authorization"),
        supervisor=supervisor, clock=clock, rpc_timeout=10)
    core = LifecycleCoreCallbacks(f.recovery.projects, journal_generation=1)

    def profile_authority(actual):
        assert actual is driver and driver.profile is profile
        f.recovery.read(PROJECT, original["operation_id"], f.secret)
        with f.authority._connect() as connection:
            assert snapshot(f, connection).binding == selected.binding

    def dummy_account_fingerprint(actual):
        assert actual is driver
        # Actual configured dummy Provider and selected environment, never an
        # invented external-account identity or an inspected user's credentials.
        material = selected_config.read_bytes()+json.dumps(profile.environment, sort_keys=True).encode()
        return hashlib.sha256(material).hexdigest()

    witness = capture_capacity_profile(driver, authorize_current=profile_authority,
                                       account_fingerprint=dummy_account_fingerprint)
    controller = ReceiverLifecycleNode(driver, config, f.node_key, clock=clock,
        resolve_original=core.resolve, require_current_execution=core.execution,
        resolve_original_read=core.read, core_session=core.session,
        profile_witness=witness, reservation_witness=reservation, fresh_capacity_seconds=30)
    node_key = private/"node.seed"
    node_key.write_text(f.node_key.encode().hex(), encoding="ascii")
    node_key.chmod(0o600)
    values = {field.name: getattr(config, field.name) for field in fields(ReceiverClientConfig)}
    runtime = ReceiverRuntimeConfig(**values, tls_cert_path=str(cert), tls_key_path=str(tls_key),
        node_signing_key_path=str(node_key), ledger_path=str(private/"transport.sqlite"),
        drop_response_after_commit_once=EXECUTE if lost_ack else None)
    forbidden = lambda *_args: pytest.fail("ordinary Native delivery must not be entered")
    server = ReceiverHTTPServer(runtime, f.node_key, forbidden, forbidden, clock=clock, lifecycle_node=controller)
    request_diagnostics = []
    original_handle = server.lifecycle.handle

    def measured_handle(path, raw):
        started = time.monotonic()
        item = {"path": path}
        try:
            response = original_handle(path, raw)
            if hasattr(response, "observation"):
                item.update(observed_at=response.observation.capacity.observed_at.isoformat(),
                            valid_until=response.observation.capacity.valid_until.isoformat())
            return response
        except Exception as error:
            item.update(error_type=type(error).__name__, code=getattr(error, "code", None),
                        frames=[(Path(frame.filename).name, frame.lineno) for frame in traceback.extract_tb(error.__traceback__)])
            raise
        finally:
            item["elapsed_seconds"] = round(time.monotonic()-started, 4)
            request_diagnostics.append(item)

    server.lifecycle.handle = measured_handle
    worker = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
    worker.start()
    facts = {"evidence_class": "actual_Core_PG_TLS_Node_WindowsJob_Codex0166_lifecycle_no_model",
             "execution_mode": "owner/native", "lost_ack": lost_ack, "model_prompts": 0}
    try:
        remote = RemoteNodeTransport(config, timeout=30, clock=clock)
        f.recovery.authority._receiver_lifecycle_transports = {RECEIVER: RemoteLifecycleTransport(remote, f.authority_key)}
        first = f.recovery.advance(PROJECT, original["operation_id"], f.secret)
        facts["first_state"] = first["state"]
        if lost_ack:
            assert first["state"] == "unknown" and first["effect_state"] == "native_possible"
            result = f.recovery.advance(PROJECT, original["operation_id"], f.secret)
        else:
            result = first
        saved = payload(f, original)
        facts.update(final_state=result["state"], reason=result.get("reason_code"), node_rejection=controller._last_rejection)
        assert result["state"] == "completed", facts
        assert driver.thread_id and driver.session_id
        row = journal.read(saved["lifecycle"]["plan"]["driver_operation_id"])
        assert row["state"] == "acknowledged" and "message_id" not in row["input"]
        with journal._connect() as connection:
            events = [(kind, json.loads(body)) for kind, body in connection.execute(
                "SELECT kind,body FROM driver_events ORDER BY sequence")]
        methods = [body.get("method") for kind, body in events if kind == "rpc_dispatch"]
        assert methods.count("thread/start") == 1 and "turn/start" not in methods and "thread/resume" not in methods
        assert sum(kind == "process_started" for kind, _ in events) == 1
        assert f.recovery.advance(PROJECT, original["operation_id"], f.secret) == result
        assert saved["lifecycle"]["receipt"]["receipt"]["outcome"] == "acknowledged"
        bound_identity = (driver.thread_id, driver.session_id)
        again = submit(f, "prepare_receiver")
        already = f.recovery.advance(PROJECT, again["operation_id"], f.secret)
        assert already["state"] == "completed" and already["reason_code"] == "lifecycle_already_ready", already
        warm = submit(f, "resume_receiver")
        observations = []
        for _ in range(3):
            resumed = f.recovery.advance(PROJECT, warm["operation_id"], f.secret)
            observations.append({"state": resumed["state"], "reason": resumed.get("reason_code")})
            if resumed["state"] != "deferred" or resumed["effect_state"] != "committed":
                break
            # An expired observation before a possible-effect marker is an
            # ordinary deferred operation. Reobserve that same operation;
            # never create another management request or replay unknown effects.
        facts.update(warm_resume_state=resumed["state"], warm_resume_reason=resumed.get("reason_code"),
                     warm_node_rejection=controller._last_rejection, warm_observation_attempts=observations)
        warm_saved = payload(f, warm).get("lifecycle", {})
        facts["warm_permit_window"] = {key: (warm_saved.get("permit") or {}).get("permit", {}).get(key)
                                        for key in ("issued_at", "deadline")}
        assert resumed["state"] == "completed", resumed
        assert (driver.thread_id, driver.session_id) == bound_identity
        with journal._connect() as connection:
            final_events = [(kind, json.loads(body)) for kind, body in connection.execute(
                "SELECT kind,body FROM driver_events ORDER BY sequence")]
        final_methods = [body.get("method") for kind, body in final_events if kind == "rpc_dispatch"]
        assert final_methods.count("thread/start") == 1 and "turn/start" not in final_methods
        assert sum(kind == "process_started" for kind, _ in final_events) == 1
        no_message_or_input(f)
        facts.update(native_creation_count=1, native_thread_and_session_observed=True,
                     actual_driver_history_mode=profile.history_mode, rpc_methods=final_methods,
                     original_ack_retained=True, existing_prepare_without_second_creation=True,
                     warm_resume_same_identity=True, no_natural_messages_or_replies=True)
    finally:
        server.shutdown()
        worker.join(timeout=6)
        server.server_close()
        if driver.owned is not None:
            proof = supervisor.terminate_tree(driver.owned)
            facts["owned_tree_stopped"] = (proof.get("verified") is True and proof.get("root_exited") is True
                                            and proof.get("remaining_pids") == [])
        controller.close()
        driver.detach_transport()
        supervisor.close()
        assert not worker.is_alive()
        evidence = os.environ.get("ACS_NATIVE_LIFECYCLE_EVIDENCE_DIR")
        if evidence:
            output = Path(evidence)
            output.mkdir(exist_ok=True)
            facts["request_diagnostics"] = request_diagnostics
            (output/("actual-lifecycle-"+("lost_ack" if lost_ack else "normal")+".json")).write_text(
                json.dumps(facts, indent=2)+"\n", encoding="utf-8")
        assert facts.get("owned_tree_stopped") is True
