"""Actual Core PG -> signed TLS -> Node/Driver SQLite; Native APIs are controlled.

No Native process, model, production service or external Host is contacted.
Enrollment, original issuer admission, current read authority and TLS pins are
real. Process creation and Native session responses remain explicit fixtures.
"""
from __future__ import annotations

import json
import os
import threading
import time
import traceback
from dataclasses import asdict, fields, replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from runtime.codex_driver import BindingIdentity, CodexAppServerDriver
from runtime.connection_clock import ConnectionClock
from runtime.receiver_config import (
    ReceiverClientConfig,
    ReceiverRuntimeConfig,
    receiver_clock_identity,
)
from runtime.receiver_crypto import key_fingerprint
from runtime.receiver_lifecycle_capacity import capture_capacity_profile
from runtime.receiver_lifecycle_core import LifecycleCoreCallbacks
from runtime.receiver_lifecycle_node import ReceiverLifecycleNode
from runtime.receiver_lifecycle_transport import EXECUTE, RemoteLifecycleTransport
from runtime.remote_endpoint import ReceiverHTTPServer, RemoteNodeTransport
from runtime.supervisor import OwnedProcess
from runtime_tests.probe_receiver_windows_backend import private_root
from runtime_tests.test_communication import comm as comm_fixture
from runtime_tests.test_communication import send
from runtime_tests.test_receiver_lifecycle_capacity import configured_capacity, file_hash
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

comm = comm_fixture


@pytest.mark.parametrize("harness", ["codex", "opencode"])
@pytest.mark.parametrize("lost_ack", [False, True])
@pytest.mark.parametrize("source_kind", ["recovery", "message"])
def test_core_recovery_over_real_tls_to_actual_controller_reads_original_ack_without_second_creation(comm, tmp_path, harness, lost_ack, source_kind):
    private = tmp_path / "receiver-private"
    if os.name == "nt":
        private_root(private)
    else:
        private.mkdir(mode=0o700)
    cert, tls_key, fingerprint = certificate(private)
    f = setup_graph(comm, locator_port=free_port(), tls_certificate_sha256=fingerprint)
    with f.authority._connect() as connection:
        selected = snapshot(f, connection)
    registration = selected.binding.registration
    identity = BindingIdentity(registration.node_id, registration.boot_incarnation, registration.runtime_id,
        "explicit-controlled-capacity", registration.agent_slot_id, registration.node_binding_revision)
    config = ReceiverClientConfig(selected.binding, selected.authority_key.key_id, selected.authority_key.revision,
        selected.authority_key.public_key, key_fingerprint(selected.authority_key.public_key), registration.boot_incarnation, 1)
    clock = ConnectionClock.local(f.authority.canonical_now, identity=receiver_clock_identity(config))
    if source_kind == "message":
        original = send(comm)["data"]
        f.authority._receiver_message_wake_policy = lambda endpoint_id: endpoint_id == RECEIVER
        f.authority._receiver_lifecycle_catalog = f.recovery.projects.catalog
    else:
        original = submit(f)

    def read_payload():
        if source_kind == "recovery":
            return payload(f, original)
        from runtime.communication_message_wake import MessageWakeStore

        with f.authority._connect() as connection:
            return MessageWakeStore(f.recovery.projects)._row(connection.cursor(), PROJECT, original["operation_id"])

    def advance():
        if source_kind == "recovery":
            return f.recovery.advance(PROJECT, original["operation_id"], f.secret)
        with f.authority._connect() as connection:
            connection.execute("UPDATE delivery_messages SET next_attempt_at=clock_timestamp()-interval '1 second' WHERE operation_id=%s",
                (original["operation_id"],))
        comm.dispatcher.dispatch({"tenant_id": f.authority.tenant_id, "message_id": original["message_id"],
            "operation_id": original["operation_id"]})
        return read_payload()["operation"]
    effects, native_reads = [], []
    with configured_capacity(harness, tmp_path, binding=identity) as capacity:
        driver = capacity.driver
        driver.supervisor.launch = lambda *_args, **_kwargs: pytest.fail("actual process launch is forbidden")
        schema = Path(__file__).parent / ("schema-0.153.2/codex_app_server_protocol.schemas.json"
            if harness == "codex" else "schema-1.18.27/opencode-openapi.json")
        capacity.schema.write_bytes(schema.read_bytes())
        driver.profile = replace(driver.profile, schema_sha256=file_hash(capacity.schema))
        driver.clock = driver.journal.clock = clock
        witness = capture_capacity_profile(driver, authorize_current=capacity.authorize,
            account_fingerprint=capacity.account_reader)

        class Native:
            endpoint = "controlled-no-network"

            def diagnostics(self):
                return {"controlled": True}

            def drain_events(self):
                return []

            def request(self, method, params=None, payload=None, **options):
                core._current()  # Raises if an authority transaction survived into Native I/O.
                options["before_send"]()
                if options.get("on_dispatch"):
                    options["on_dispatch"]()
                if harness == "codex":
                    if method in {"thread/read", "thread/turns/list"}:
                        assert params["threadId"] == "controlled_original_thread"
                        native_reads.append((method, params))
                        if method == "thread/turns/list":
                            return {"data": []}
                        return {"thread": {"id": "controlled_original_thread", "sessionId": "controlled_original_provider",
                            "status": {"type": "idle"}}, "cwd": driver.profile.cwd}
                    assert method == "thread/start"
                    effects.append((method, params))
                    return {"thread": {"id": "controlled_original_thread", "sessionId": "controlled_original_provider"}}
                original_session = {"id": "ses_original", "version": "controlled-native", "projectID": "project",
                    "directory": driver.profile.cwd, "title": "controlled session",
                    "time": {"created": 1, "updated": 1},
                    "metadata": {"acs_binding_id": driver.binding_id, "acs_binding": asdict(driver.identity),
                        "acs_operation_id": "original-owned-process"}}
                if method == "GET":
                    permitted = {"/doc": json.loads(capacity.schema.read_text()), "/config": {},
                        "/session/ses_original": original_session, "/session/ses_original/message": [],
                        "/session/status": {"ses_original": {"type": "idle"}}, "/permission": [], "/question": []}
                    assert params in permitted, "unrelated Native reads are forbidden"
                    native_reads.append((method, params))
                    return 200, permitted[params]
                assert (method, params) == ("POST", "/session"), "additional Native writes are forbidden"
                effects.append((method, params))
                return 200, original_session

        def spawn(operation):
            def perform():
                core._current()
                # The exact execution plan and native_possible marker are
                # committed before any process/protocol fixture is entered.
                with f.authority._connect() as connection:
                    saved = connection.execute("SELECT payload FROM outbox WHERE tenant_id=%s AND operation_id=%s "
                        "FOR UPDATE NOWAIT", (f.authority.tenant_id, original["operation_id"])).fetchone()[0]
                    saved = saved.get("receiver_wake", saved)
                    assert saved["operation"]["effect_state"] == "native_possible"
                    assert saved["lifecycle"]["phase"] == "executing"
                driver.check_current(operation, driver.identity)
                driver.journal.event(operation.operation_id, "process_dispatch", {"binding": asdict(identity)})
                driver.owned = OwnedProcess(SimpleNamespace(pid=49152, poll=lambda: None),
                    "actual-controlled-job", "actual-controlled-birth")
                driver.client, driver.ownership = Native(), "exclusive_owned"
                driver.journal.event(operation.operation_id, "process_started", {"pid": 49152,
                    "birth_ref": "actual-controlled-birth", "containment_id": "actual-controlled-job"})
                if isinstance(driver, CodexAppServerDriver):
                    result = driver._rpc(operation, "thread/start", {"cwd": driver.profile.cwd})
                    driver.thread_id, driver.session_id = result["thread"]["id"], result["thread"]["sessionId"]
                    return driver._binding_receipt("runtime_acknowledged")
                _status, result = driver._http(operation, "POST", "/session", {})
                driver.session_id = result["id"]
                return driver._receipt("runtime_acknowledged", native_ack_type="session_create_response")
            return driver._run(operation, "spawn", {"profile": driver.profile.binding()}, perform)

        driver.spawn = spawn

        core = LifecycleCoreCallbacks(f.recovery.projects, journal_generation=1)
        core_failures = []

        def checked(name, callback):
            def call(*args):
                try:
                    return callback(*args)
                except Exception as error:
                    core_failures.append({"phase": name, "type": type(error).__name__, "code": getattr(error, "code", None),
                        "frames": [(Path(frame.filename).name, frame.lineno) for frame in traceback.extract_tb(error.__traceback__)]})
                    raise
            return call

        controller = ReceiverLifecycleNode(driver, config, f.node_key, clock=clock,
            resolve_original=checked("resolve", core.resolve), require_current_execution=checked("execute", core.execution),
            resolve_original_read=checked("read", core.read), core_session=core.session,
            profile_witness=witness, reservation_witness=capacity.reservation, fresh_capacity_seconds=30)
        node_key = private / "node.seed"
        node_key.write_text(f.node_key.encode().hex(), encoding="ascii")
        node_key.chmod(0o600)
        values = {field.name: getattr(config, field.name) for field in fields(ReceiverClientConfig)}
        runtime = ReceiverRuntimeConfig(**values, tls_cert_path=str(cert), tls_key_path=str(tls_key),
            node_signing_key_path=str(node_key), ledger_path=str(private / "node.sqlite"),
            drop_response_after_commit_once=EXECUTE if lost_ack else None)
        forbidden = lambda *_args: pytest.fail("ordinary delivery callback was entered")
        server = ReceiverHTTPServer(runtime, f.node_key, forbidden, forbidden, clock=clock, lifecycle_node=controller)
        failures, timings, observed_times = [], [], []
        actual_handle = server.lifecycle.handle

        def measured(path, raw):
            started = time.monotonic()
            try:
                value = actual_handle(path, raw)
                if hasattr(value, "observation"):
                    observed_times.append((value.observation.capacity.observed_at.isoformat(),
                        value.observation.capacity.valid_until.isoformat()))
                return value
            except Exception as error:
                failures.append({"type": type(error).__name__, "code": getattr(error, "code", None),
                    "frames": [(Path(frame.filename).name, frame.lineno) for frame in traceback.extract_tb(error.__traceback__)]})
                raise
            finally:
                timings.append((path, time.monotonic() - started))

        server.lifecycle.handle = measured
        worker = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
        worker.start()
        try:
            remote = RemoteNodeTransport(config, timeout=30, clock=clock)
            f.recovery.authority._receiver_lifecycle_transports = {RECEIVER: RemoteLifecycleTransport(remote, f.authority_key)}
            try:
                result = advance()
            except Exception as error:
                error.add_note(json.dumps({"timings": timings, "observed": observed_times,
                    "core_now": f.authority.canonical_now().isoformat(), "errors": failures}))
                raise
            if lost_ack:
                assert result["state"] == "unknown" and result["effect_state"] == "native_possible", (result, failures, timings)
                assert len(effects) == 1
                result = advance()
            saved = read_payload()
            details = {"state": result["state"], "reason": result["reason_code"], "errors": failures, "timings": timings,
                "observed": observed_times, "core_now": f.authority.canonical_now().isoformat(),
                "permit_window": [(saved.get("lifecycle", {}).get("permit") or {}).get("permit", {}).get(field)
                    for field in ("issued_at", "deadline")],
                "receipt_reason": saved.get("lifecycle", {}).get("receipt", {}).get("receipt", {}).get("reason_code"),
                "core_failures": core_failures, "node_rejection": controller._last_rejection}
            assert result["state"] == "completed", json.dumps(details)
            assert result["operation_id"] == original["operation_id"] and len(effects) == 1
            if source_kind == "message" and lost_ack:
                assert native_reads, "the completed original wake is reobserved without another Native creation"
            assert advance() == result
            assert len(effects) == 1
            stored = read_payload()
            assert stored["lifecycle"]["receipt"]["receipt"]["outcome"] == "acknowledged"
            row = driver.journal.read(stored["lifecycle"]["plan"]["driver_operation_id"])
            assert row["state"] == "acknowledged" and "message_id" not in row["input"]
            if source_kind == "recovery":
                no_message_or_input(f)
            else:
                assert len(comm.drivers["b"].calls) == 1
                with f.authority._connect() as connection:
                    assert connection.execute("SELECT count(*) FROM communication_replies").fetchone() == (0,)
                    assert connection.execute("SELECT count(*) FROM outbox WHERE topic='communication.receiver.recovery'").fetchone() == (0,)
                    assert connection.execute("SELECT count(*) FROM delivery_messages").fetchone() == (1,)
        finally:
            server.shutdown()
            worker.join(timeout=6)
            server.server_close()
            controller.close()
            assert not worker.is_alive()
