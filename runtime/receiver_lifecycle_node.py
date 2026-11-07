"""Programmatic signed lifecycle controller over the actual exclusively owned Driver.

Core callbacks must load original Domain rows in their own closed transactions.
This module creates no persistent ledger, transport, process or input owner. The
only execution path is the existing Driver spawn/resume and its original journal.
Production factory and Core transport mounting are deliberately separate.

resolve_original_read must use an actual current authenticated Core caller
context and authorize the exact stored original permit/scope. An old permit
selects history; neither its old signature nor this class's local read timer is
fresh network read authorization. A future network mount must supply that
authenticated hook or a fresh signed readback-purpose nonce/window contract.
"""
from __future__ import annotations

import json
import secrets
import sqlite3
import threading
from contextlib import contextmanager, nullcontext
from dataclasses import asdict, dataclass
from datetime import timedelta
from pathlib import Path

from nacl.signing import SigningKey

from runtime.codex_driver import CodexAppServerDriver, DriverRejected
from runtime.connection_clock import ConnectionClock
from runtime.native_input_observations import observe_native_input
from runtime.opencode_driver import OpenCodeNativeDriver
from runtime.receiver_config import ReceiverClientConfig
from runtime.receiver_contract import native_generation
from runtime.receiver_crypto import public_key, sha256, verify
from runtime.receiver_lifecycle import AuthorizedLifecycleOperation
from runtime.receiver_lifecycle_capacity import (
    CapturedCapacityProfile,
    _birth_identity,
    _claim,
    _file_stamp,
    _journal,
    _owned_process,
    _ref,
    capacity_profile_seal,
    observe_receiver_capacity,
)
from runtime.receiver_lifecycle_contract import (
    CapacityObservation,
    LifecycleReceipt,
    LifecycleSource,
    SignedCapacityObservation,
    SignedLifecycleChallenge,
    SignedLifecyclePermit,
    build_lifecycle_plan,
    capacity_restore_ref,
    sign_observation,
    sign_receipt,
    verify_challenge,
    verify_permit,
)
from runtime.receiver_lifecycle_domain import LifecycleEndpointSnapshot
from runtime.receiver_lifecycle_read import AuthorizedLifecycleObservation


class LifecycleNodeRejected(DriverRejected):
    def __init__(self, code):
        self.code = code
        super().__init__("Node lifecycle authorization or evidence is unavailable")


def _typed(model, value):
    if type(value) is not model:
        raise LifecycleNodeRejected("lifecycle_typed_contract_required")
    try:
        return model.model_validate(value, strict=True)
    except (ValueError, TypeError) as error:
        raise LifecycleNodeRejected("lifecycle_contract_invalid") from error


@dataclass
class _Lease:
    operation: object
    source: LifecycleSource
    target: object
    deadline: object
    kind: str
    permit: SignedLifecyclePermit | None
    stamps: dict
    owner: tuple


class ReceiverLifecycleNode:
    def __init__(self, driver, config, node_signing_key, *, clock, resolve_original,
                 require_current_execution, resolve_original_read, profile_witness=None,
                 reservation_witness=None, max_capabilities=16, core_session=None, fresh_capacity_seconds=15):
        if (not isinstance(driver, (CodexAppServerDriver, OpenCodeNativeDriver))
                or not isinstance(config, ReceiverClientConfig) or type(node_signing_key) is not SigningKey
                or not isinstance(clock, ConnectionClock) or driver.clock is not clock
                or not all(callable(callback) for callback in (resolve_original, require_current_execution, resolve_original_read))
                or type(max_capabilities) is not int or not 1 <= max_capabilities <= 64):
            raise TypeError("actual Driver, installed receiver trust and independent current Core callbacks required")
        ReceiverClientConfig.validate(config)
        if (public_key(node_signing_key) != config.binding.node_public_key
                or type(config.authority_key_revision) is not int or config.authority_key_revision < 1
                or type(config.journal_generation) is not int or config.journal_generation < 1):
            raise LifecycleNodeRejected("lifecycle_installed_node_key_mismatch")
        registration = config.binding.registration
        if ((driver.identity.node_id, driver.identity.node_boot_id, driver.identity.runtime_id,
             driver.identity.agent_slot_id, driver.identity.revision) !=
                (registration.node_id, registration.boot_incarnation, registration.runtime_id,
                 registration.agent_slot_id, registration.node_binding_revision)):
            raise LifecycleNodeRejected("lifecycle_actual_driver_binding_mismatch")
        if isinstance(getattr(driver.check_current, "__self__", None), ReceiverLifecycleNode):
            raise LifecycleNodeRejected("lifecycle_driver_already_has_controller")
        self.driver, self.config, self.clock, self.signing_key = driver, config, clock, node_signing_key
        self.resolve_original, self.require_current_execution = resolve_original, require_current_execution
        self.resolve_original_read = resolve_original_read
        if core_session is not None and not callable(core_session):
            raise TypeError("Core session must be a trusted context factory")
        self._core_session = core_session or nullcontext
        if type(fresh_capacity_seconds) is not int or not 1 <= fresh_capacity_seconds <= 30:
            raise ValueError("fresh private capacity must fit the lifecycle transport bound")
        self._fresh_capacity_seconds = fresh_capacity_seconds
        self.profile_witness, self.reservation_witness = profile_witness, reservation_witness
        if profile_witness is not None:
            driver._lifecycle_profile_seal = capacity_profile_seal(profile_witness)
        self._binding, self._profile, self._journal, self._supervisor = driver.identity, driver.profile, driver.journal, driver.supervisor
        self._original_check, self._check = driver.check_current, self._check_current
        self._lock, self._leases, self._closed, self._maximum = threading.RLock(), {}, False, max_capabilities
        self._installed = False
        self._last_rejection = None  # Private typed diagnostic; never a wire exception body.
        self._fixed()
        try:
            self._history_journal_identity = _journal(driver)["identity"]
        except Exception:  # noqa: BLE001 - unreadable history must remain unknown, never fresh.
            self._history_journal_identity = None
        driver.check_current = self._check
        self._installed = True

    def _session(self):
        return self.driver.thread_id if isinstance(self.driver, CodexAppServerDriver) else self.driver.session_id

    def _fixed(self):
        driver, config = self.driver, self.config
        if (self._closed or driver.identity != self._binding or driver.profile is not self._profile
                or driver.journal is not self._journal or driver.supervisor is not self._supervisor
                or driver.clock is not self.clock or public_key(self.signing_key) != config.binding.node_public_key
                or driver.check_current is not (self._check if self._installed else self._original_check)):
            raise LifecycleNodeRejected("lifecycle_node_ownership_changed")
        registration = config.binding.registration
        expected = {"authority_id": registration.authority_id, "authority_incarnation": registration.authority_incarnation,
            "node_id": registration.node_id, "boot_incarnation": registration.boot_incarnation,
            "machine_id": registration.machine_id, "endpoint_id": registration.endpoint_id}
        if any(self.clock.identity.get(name) != value for name, value in expected.items()):
            raise LifecycleNodeRejected("lifecycle_connection_clock_subject_changed")
        _claim(driver)

    def _target(self, target):
        self._fixed()
        if (target.registration != self.config.binding.registration or target.node_key_id != self.config.binding.node_key_id
                or target.journal_generation != self.config.journal_generation):
            raise LifecycleNodeRejected("lifecycle_installed_target_changed")

    def _resolve(self, stage, source, target):
        self._target(target)
        actual, snapshot = self.resolve_original(stage, source)
        if (type(actual) is not LifecycleSource or type(snapshot) is not LifecycleEndpointSnapshot
                or _typed(LifecycleSource, actual) != source or snapshot.target() != target
                or snapshot.binding != self.config.binding or snapshot.journal_generation != self.config.journal_generation
                or (snapshot.authority_key.key_id, snapshot.authority_key.revision, snapshot.authority_key.public_key,
                    snapshot.authority_key.fingerprint) !=
                   (self.config.authority_key_id, self.config.authority_key_revision, self.config.authority_public_key,
                    self.config.authority_public_key_fingerprint)):
            raise LifecycleNodeRejected("lifecycle_current_core_subject_changed")
        if snapshot.valid_until is not None:
            self.clock.require_before(snapshot.valid_until)
        self._target(target)

    def _history_authority(self, signed):
        source, target = signed.permit.plan.source, signed.permit.plan.target
        self._target(target)
        if _typed(LifecycleSource, self.resolve_original_read(signed)) != source:
            raise LifecycleNodeRejected("lifecycle_original_read_subject_changed")
        self._target(target)

    def _authority(self, lease):
        if lease.kind == "history":
            self._history_authority(lease.permit)
        elif lease.permit is not None:
            # This complete Core check already validates the exact persisted
            # source, current target and committed permit. A second full source
            # lookup would only repeat that same check before the effect.
            if self.require_current_execution(lease.permit) is not None:
                raise LifecycleNodeRejected("lifecycle_current_execution_rejected")
        else:
            self._resolve(lease.kind, lease.source, lease.target)
        self.clock.require_before(lease.deadline)

    def _stamps(self):
        profile = self.driver.profile
        config = Path(profile.codex_home) / "config.toml" if isinstance(self.driver, CodexAppServerDriver) else profile.config_path
        return {str(path): _file_stamp(Path(path).lstat()) for path in (profile.executable, profile.schema_path, config)}

    def _profile_current(self, lease, *, account=True):
        witness = self.profile_witness
        if (type(witness) is not CapturedCapacityProfile or witness._driver is not self.driver
                or witness._profile is not self.driver.profile or witness.binding != self.driver.identity
                or witness._memory_fingerprint != sha256({"value": {"profile": self.driver.profile.binding(),
                    "environment": self.driver.profile.environment}}) or self._stamps() != lease.stamps
                or _birth_identity(Path(self.driver.journal.path).lstat()) != witness._journal_identity):
            raise LifecycleNodeRejected("lifecycle_profile_witness_changed")
        if account and witness._account_reader(self.driver) != witness.account_fingerprint:
            raise LifecycleNodeRejected("lifecycle_account_witness_changed")
        if lease.kind == "execute":
            if self.driver.owned is None:
                if getattr(lease.operation, "restore_process_ref", None) is not None:
                    from runtime.native_restore import stopped_process

                    if (self.driver.client is not None or self.driver.ownership != "exclusive_reserved_restore"
                            or stopped_process(self.driver)["evidence_ref"] != lease.operation.restore_process_ref):
                        raise LifecycleNodeRejected("lifecycle_exclusive_ownership_changed")
                elif (lease.operation.action != "spawn" or self.driver.ownership != "unbound"
                        or self.driver.client is not None or self._session() is not None):
                    raise LifecycleNodeRejected("lifecycle_exclusive_ownership_changed")
            elif self.driver.ownership != "exclusive_owned":
                raise LifecycleNodeRejected("lifecycle_exclusive_ownership_changed")
        if ((isinstance(lease.operation, AuthorizedLifecycleObservation)
                or lease.kind == "execute" and lease.operation.action == "resume")
                and (id(self.driver.owned), id(self.driver.client)) != lease.owner):
            actual = (id(self.driver.owned), id(self.driver.client))
            if (lease.kind != "execute" or getattr(lease.operation, "restore_process_ref", None) is None
                    or actual != getattr(self.driver, "_owned_transport_identity", None)):
                raise LifecycleNodeRejected("lifecycle_original_process_handle_changed")
            # A transport replacement is allowed only after this exact resume
            # operation durably records the newly owned process. Pin its actual
            # client once; subsequent callback-time replacement is still denied.
            process = _owned_process(self.driver)
            record = self._record(lease.permit.permit.plan)
            if record is None or not any(kind == "process_started" and
                    (body.get("pid"), body.get("birth_ref"), body.get("containment_id")) ==
                    (process.pid, process.birth_ref, process.containment_id) for kind, body in record["events"]):
                raise LifecycleNodeRejected("lifecycle_original_created_process_changed")
            lease.owner = actual
        if self.driver.owned is not None:
            poll = getattr(self.driver.owned.process, "poll", None)
            if callable(poll) and poll() is not None:
                from runtime.native_restore import stopped_process

                process = stopped_process(self.driver)
                if lease.kind == "execute" and process["evidence_ref"] != getattr(lease.operation, "restore_process_ref", None):
                    raise LifecycleNodeRejected("lifecycle_original_stopped_process_changed")
                return
            process = _owned_process(self.driver)
            if lease.kind == "execute" and lease.operation.action == "spawn":
                record = self._record(lease.permit.permit.plan)
                if record is None or not any(kind == "process_started" and
                        (body.get("pid"), body.get("birth_ref"), body.get("containment_id")) ==
                        (process.pid, process.birth_ref, process.containment_id) for kind, body in record["events"]):
                    raise LifecycleNodeRejected("lifecycle_original_created_process_changed")

    def _local(self, operation, clock=None):
        with self._lock:
            self._fixed()
            lease = self._leases.get(id(operation))
            if lease is None or lease.operation is not operation or clock is not None and clock is not self.clock:
                raise LifecycleNodeRejected("lifecycle_exact_capability_required")
            self.clock.require_before(lease.deadline)
            if lease.kind != "history" and lease.source.business_deadline is not None:
                self.clock.require_before(lease.source.business_deadline)
            operation.check_target(self.driver.binding_id, self.driver.identity, self._session())
            return lease

    def _check_current(self, operation, identity):
        if isinstance(operation, (AuthorizedLifecycleOperation, AuthorizedLifecycleObservation)):
            if type(operation) not in (AuthorizedLifecycleOperation, AuthorizedLifecycleObservation) or identity != self.driver.identity:
                raise LifecycleNodeRejected("lifecycle_exact_capability_required")
            lease = self._local(operation, self.clock)
            if lease.kind != "history":
                self._profile_current(lease)
            self._authority(lease)
            if lease.kind != "history":
                self._profile_current(lease, account=False)
            self._local(operation, self.clock)
            return
        if str(getattr(operation, "operation_id", "")).startswith("receiver-lifecycle"):
            raise LifecycleNodeRejected("lifecycle_exact_capability_required")
        return self._original_check(operation, identity)

    @contextmanager
    def _lease(self, source, target, deadline, kind, permit=None, operation=None):
        self._fixed()
        if operation is None:
            selected = self._session()
            generation = native_generation(self.driver.binding_id, asdict(self.driver.identity), selected) if selected is not None else None
            operation = AuthorizedLifecycleObservation("receiver-lifecycle-read:" + secrets.token_hex(32), source.command_id,
                source.operation_ref, source.grant_ref, deadline, self.driver.binding_id, self.driver.identity,
                selected, generation, self._local)
        try:
            stamps = self._stamps()
        except OSError:
            stamps = {}
        record = _Lease(operation, source, target, deadline, kind, permit, stamps,
                        (id(self.driver.owned), id(self.driver.client)))
        with self._lock:
            if len(self._leases) >= self._maximum:
                raise LifecycleNodeRejected("lifecycle_capability_limit")
            self._leases[id(operation)] = record
        try:
            yield operation
        finally:
            with self._lock:
                self._leases.pop(id(operation), None)

    def _key_options(self):
        return {"authority_key_id": self.config.authority_key_id, "authority_key_revision": self.config.authority_key_revision,
                "authority_public_key": self.config.authority_public_key, "clock": self.clock}

    def _current_callback(self, stage, source, target):
        self._resolve(stage, source, target)

    def observe(self, signed_challenge):
        signed = _typed(SignedLifecycleChallenge, signed_challenge)
        with self.driver._lock, self._core_session():
            self._fixed()
            challenge = verify_challenge(signed, expected_source=signed.challenge.source, actual_target=signed.challenge.target,
                authorize_current=self._current_callback, **self._key_options())
            with self._lease(challenge.source, challenge.target, challenge.deadline, "challenge") as operation:
                capacity = self._capacity(operation)
                observation = CapacityObservation(challenge_digest=sha256(challenge), request_id=challenge.request_id,
                    nonce=challenge.nonce, source_digest=sha256(challenge.source), target=challenge.target,
                    node_key_id=self.config.binding.node_key_id, capacity=capacity)
                self.clock.require_before(min(challenge.deadline, capacity.valid_until))
                result = sign_observation(observation, self.signing_key)
                self._capacity_authority(operation, self.driver)
                self.clock.require_before(min(challenge.deadline, capacity.valid_until))
                return result

    def _capacity_authority(self, operation, actual):
        if actual is not self.driver:
            raise LifecycleNodeRejected("lifecycle_actual_driver_binding_mismatch")
        self._authority(self._local(operation, self.clock))
        self._local(operation, self.clock)

    def _capacity(self, operation):
        self._capacity_authority(operation, self.driver)

        def local(actual):
            if actual is not self.driver:
                raise LifecycleNodeRejected("lifecycle_actual_driver_binding_mismatch")
            # File/claim/profile reads are local and immutable under this
            # Driver lock. Check their exact capability and deadlines between
            # reads; current Core authority brackets the whole observation.
            # The actual Native read still uses the Driver's full final fence.
            self._local(operation, self.clock)

        result = observe_receiver_capacity(self.driver, authorize_current=local,
            profile_witness=self.profile_witness, reservation_witness=self.reservation_witness,
            native_readback=lambda actual: observe_native_input(actual, operation), ttl_seconds=5,
            fresh_ttl_seconds=self._fresh_capacity_seconds)
        self._capacity_authority(operation, self.driver)
        return result

    def _artifacts(self, signed_permit, challenge, observation):
        signed, challenge, observation = (_typed(SignedLifecyclePermit, signed_permit),
            _typed(SignedLifecycleChallenge, challenge), _typed(SignedCapacityObservation, observation))
        permit, c, o = signed.permit, challenge.challenge, observation.observation
        self._target(permit.plan.target)
        if (permit.plan.capacity.driver_binding_id != self.driver.binding_id or permit.plan.capacity.binding != self._binding):
            raise LifecycleNodeRejected("lifecycle_original_driver_capacity_changed")
        if ((permit.authority_key_id, permit.authority_key_revision, c.authority_key_id, c.authority_key_revision) !=
                (self.config.authority_key_id, self.config.authority_key_revision,
                 self.config.authority_key_id, self.config.authority_key_revision)
                or permit.plan != build_lifecycle_plan(c, o, permit.plan.action)
                or (permit.challenge_digest, permit.observation_digest, permit.request_id, permit.nonce) !=
                   (sha256(c), sha256(o), c.request_id, c.nonce)):
            raise LifecycleNodeRejected("lifecycle_original_artifacts_changed")
        verify(self.config.authority_public_key, challenge.signature, c)
        verify(self.config.binding.node_public_key, observation.signature, o)
        verify(self.config.authority_public_key, signed.signature, permit)
        return signed, c, o

    def _record(self, plan):
        history = _journal(self.driver)
        # Historical ACK metadata needs the retained, claimed journal, not a
        # pre-launch profile witness that cannot be recreated after a restart.
        # Execution still independently requires its original capacity profile.
        if self._history_journal_identity is None or history["identity"] != self._history_journal_identity:
            raise LifecycleNodeRejected("lifecycle_original_journal_unavailable")
        path = Path(self.driver.journal.path).absolute()
        connection = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, isolation_level=None, timeout=2)
        try:
            connection.execute("BEGIN")
            self.driver.journal._verify_lifecycle_schema(connection)
            row = connection.execute("SELECT " + self.driver.journal._operation_columns(2) +
                " FROM driver_operations WHERE operation_id=?", (plan.driver_operation_id,)).fetchone()
            events = connection.execute("SELECT kind,body FROM driver_events WHERE operation_id=? ORDER BY sequence",
                                        (plan.driver_operation_id,)).fetchall()
            if row is None:
                if events:
                    raise LifecycleNodeRejected("lifecycle_original_journal_unavailable")
                return None
            self.driver.journal._verify_operation_row(row, 2)
            body = json.loads(row[6])
            if ((row[1], row[2], row[3], row[4], row[9], row[10]) !=
                    (plan.capacity.driver_binding_id, plan.source.command_id, None, plan.action, "receiver_lifecycle", plan.source.operation_ref)
                    or body.get("grant_ref") != plan.source.grant_ref
                    or body.get("deadline") != (plan.source.business_deadline.isoformat() if plan.source.business_deadline else None)
                    or body.get("payload", {}).get("binding") != asdict(plan.capacity.binding)):
                raise LifecycleNodeRejected("lifecycle_original_journal_subject_changed")
            if body.get("restore_process_ref") != capacity_restore_ref(plan.capacity):
                raise LifecycleNodeRejected("lifecycle_original_restore_process_changed")
            seal = body.get("payload", {}).get("capacity_profile")
            if seal is not None and seal.get("profile_fingerprint") != plan.capacity.profile_fingerprint:
                raise LifecycleNodeRejected("lifecycle_original_profile_seal_changed")
            return {"state": row[7], "result": json.loads(row[8]) if row[8] else None,
                    "events": [(kind, json.loads(data)) for kind, data in events], "evidence": "lifecycle-journal:" + sha256({"row": row, "events": events})}
        finally:
            connection.close()

    def _ack(self, plan, record):
        result, events = record["result"], record["events"]
        if (type(result) is not dict or (result.get("operation_id"), result.get("command_id"), result.get("source_kind"), result.get("source_ref"),
                result.get("binding_id"), result.get("binding"), result.get("ownership")) !=
                (plan.driver_operation_id, plan.source.command_id, "receiver_lifecycle", plan.source.operation_ref,
                 plan.capacity.driver_binding_id, asdict(plan.capacity.binding), "exclusive_owned")):
            return None
        selected = result.get("thread_id") if isinstance(self.driver, CodexAppServerDriver) else result.get("native_session_id")
        try:
            _ref(selected)
            if isinstance(self.driver, CodexAppServerDriver):
                _ref(result.get("session_id"))
        except ValueError:
            return None
        if result.get("receipt_layer") not in {"runtime_acknowledged", "context_resumed"}:
            return None
        generation = native_generation(plan.capacity.driver_binding_id, asdict(plan.capacity.binding), selected)
        if plan.action == "resume" and (selected, generation) != (plan.capacity.native_session_ref, plan.capacity.provider_generation):
            return None
        if (plan.action == "spawn" or capacity_restore_ref(plan.capacity) is not None) and not any(kind == "process_started" for kind, _body in events):
            return None
        if result.get("restore_process_ref") != capacity_restore_ref(plan.capacity):
            return None
        if isinstance(self.driver, CodexAppServerDriver):
            methods = {body.get("request_id"): body.get("method") for kind, body in events if kind == "rpc_dispatch"}
            required = {"thread/start"} if plan.action == "spawn" else {"thread/resume", "thread/read"}
            observed = any(kind == "rpc_response" and methods.get(body.get("request_id")) in required
                and body.get("result", {}).get("thread", {}).get("id") == selected
                and body["result"]["thread"].get("sessionId") == result.get("session_id") for kind, body in events)
        else:
            path = "/session" if plan.action == "spawn" else "/session/" + selected
            method = "POST" if plan.action == "spawn" else "GET"
            observed = any(kind == "http_response" and body.get("method") == method and body.get("path") == path
                and type(body.get("status")) is int and 200 <= body["status"] < 300
                and (plan.action != "spawn" or body.get("native_session_id") == selected) for kind, body in events)
        return (selected, generation) if observed else None

    def _receipt(self, signed, record, *, entered=False, reason=None):
        permit, plan = signed.permit, signed.permit.plan
        try:
            positive = self._ack(plan, record) if record is not None and record["state"] == "acknowledged" else None
        except (AttributeError, KeyError, TypeError, ValueError):
            positive = None
        dispatched = record is not None and any(kind in {"process_dispatch", "process_started"}
            or kind == "rpc_dispatch" and body.get("method") in {"thread/start", "thread/resume"}
            or kind == "http_dispatch" and body.get("method") != "GET" for kind, body in record["events"])
        if positive is not None and reason is None:
            outcome, possible, reason = "acknowledged", True, None
        elif reason is None and record is not None and record["state"] in {"rejected", "deferred"} and not dispatched:
            outcome, possible, reason = "definitively_not_started", False, "lifecycle_original_pre_dispatch_rejection"
        elif record is None and not entered:
            outcome, possible, reason = "definitively_not_started", False, reason or "lifecycle_original_not_dispatched"
        else:
            outcome, possible, reason = "unknown", True, reason or "lifecycle_original_outcome_unresolved"
        now = self.clock.observation_time()
        receipt = LifecycleReceipt(source=plan.source, target=plan.target, driver_operation_id=plan.driver_operation_id,
            action=plan.action, permit_digest=sha256(permit), semantic_digest=permit.semantic_digest,
            request_id=permit.request_id, nonce=permit.nonce, node_key_id=self.config.binding.node_key_id,
            outcome=outcome, effect_possible=possible, evidence_refs=(record["evidence"] if record else "lifecycle-node-no-dispatch:" + sha256(permit),),
            native_session_ref=positive[0] if outcome == "acknowledged" else None,
            provider_generation=positive[1] if outcome == "acknowledged" else None, reason_code=reason,
            observed_at=now, issued_at=now, deadline=now + timedelta(seconds=10),
            restore_process_ref=capacity_restore_ref(plan.capacity))
        return sign_receipt(receipt, self.signing_key)

    def execute(self, signed_permit, *, challenge, observation):
        with self.driver._lock, self._core_session():
            signed, c, o = self._artifacts(signed_permit, challenge, observation)
            plan, permit = signed.permit.plan, signed.permit
            self._history_authority(signed)
            try:
                original = self._record(plan)
            except Exception:  # noqa: BLE001 - damaged original history must not enable a new Driver entry.
                self._history_authority(signed)
                return self._receipt(signed, None, entered=True, reason="lifecycle_original_journal_unavailable")
            if original is not None:
                return self.reconcile(signed, challenge=challenge, observation=observation)
            if (self.profile_witness is None or plan.action == "spawn" and (
                    self.driver.owned is not None or self.driver.client is not None or self._session() is not None
                    or self.driver.ownership != "unbound")):
                # A lost original row is not absence proof after a creation or
                # after reconstruction without its pre-effect profile capture.
                return self._receipt(signed, None, entered=True, reason="lifecycle_original_journal_unavailable")
            self._resolve("execute", plan.source, plan.target)
            entered = False
            try:
                if self.require_current_execution(signed) is not None:
                    raise LifecycleNodeRejected("lifecycle_current_execution_rejected")
                if plan.action == "spawn" and (not callable(getattr(self.driver.supervisor, "launch", None))
                        or not callable(getattr(self.driver.supervisor, "inspect", None))):
                    raise LifecycleNodeRejected("lifecycle_owned_supervisor_unsupported")
                deadline = min(permit.deadline, c.deadline,
                    *((plan.source.business_deadline,) if plan.source.business_deadline is not None else ()))
                with self._lease(plan.source, plan.target, deadline, "preflight", signed) as read:
                    current = self._capacity(read)
                    self._check_current(read, self.driver.identity)
                operation = verify_permit(signed, challenge=c, observation=o, expected_source=plan.source,
                    actual_target=plan.target, actual_capacity=current, authorize_current=self._current_callback, **self._key_options())
                deadline = min(deadline, current.valid_until)
                with self._lease(plan.source, plan.target, deadline, "execute", signed, operation) as admitted:
                    self._check_current(admitted, self.driver.identity)
                    entered = True
                    getattr(self.driver, plan.action)(admitted)
                original = self._record(plan)
                return self.reconcile(signed, challenge=challenge, observation=observation)
            except Exception as error:  # noqa: BLE001 - possible effects never authorize a replay.
                self._last_rejection = (type(error).__name__, getattr(error, "code", None))
                try:
                    original = self._record(plan)
                except Exception:  # noqa: BLE001 - missing/corrupt history cannot prove no effect.
                    return self._receipt(signed, None, entered=True, reason="lifecycle_original_journal_unavailable")
                return self._receipt(signed, original, entered=entered,
                    reason="lifecycle_execution_or_readback_unavailable" if entered else "lifecycle_rejected_before_driver_entry")

    def reconcile(self, signed_permit, *, challenge, observation):
        """Read original facts under the mandatory fresh trusted Core read hook.

        No network read authorization is inferred from the old execution permit.
        Missing reliable original Native evidence remains unknown; this method
        does not create/restart a Session or repair it by another Native action.
        """
        with self.driver._lock, self._core_session():
            signed, _c, _o = self._artifacts(signed_permit, challenge, observation)
            plan = signed.permit.plan
            self._history_authority(signed)
            deadline = self.clock.now() + timedelta(seconds=10)
            with self._lease(plan.source, plan.target, deadline, "history", signed) as read:
                self._check_current(read, self.driver.identity)
                try:
                    original = self._record(plan)
                except Exception:  # noqa: BLE001 - current read authority can only publish unknown for damaged history.
                    original = None
                    result = self._receipt(signed, None, entered=True, reason="lifecycle_original_journal_unavailable")
                else:
                    result = self._receipt(signed, original)
                self._check_current(read, self.driver.identity)
                return result

    def close(self):
        """Revoke only this controller's ephemeral authority; no Driver close."""
        with self.driver._lock, self._lock:
            self._closed = True
            self._leases.clear()
            # Keep the revocation dispatcher: a permissive legacy callback must
            # never revive a retired message-less operation. Ordinary calls
            # still reach the exact original authorizer through this wrapper.
