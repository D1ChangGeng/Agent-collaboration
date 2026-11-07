from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from contextlib import closing
from datetime import UTC, datetime
from typing import Protocol

from runtime.delivery_models import DeliveryEnvelope, InvocationObservation, InvocationRequest
from runtime.node import RECEIPT_LAYERS, NodeJournal, OperationIdentityConflict


class DeliveryTransportError(RuntimeError):
    """No reliable ACK: retry the same message identity within its budget."""


class DeliveryBoundaryRejected(RuntimeError):
    pass


class InvocationPreCallRejected(DeliveryBoundaryRejected):
    """The Driver rejected immutable input before any native I/O was admitted."""


NATIVE_ATTACHMENT_UNSUPPORTED = "native_attachment_delivery_unsupported"


def has_native_attachments(packet):
    return getattr(packet, "schema_version", None) == "acs-message/1" and bool(getattr(packet, "attachment_refs", ()))


def reject_native_attachments(invocation):
    """No installed Driver has a qualified attachment preparation/input port."""
    if has_native_attachments(invocation.envelope.packet):
        raise InvocationPreCallRejected(NATIVE_ATTACHMENT_UNSUPPORTED)


class InvocationDeferred(InvocationPreCallRejected):
    """Keep the prepared Attempt while the target is busy/offline/unknown."""

    def __init__(self, activity="unknown"):
        self.activity = activity
        super().__init__("target_" + activity)


class InvocationDriver(Protocol):
    evidence_class: str

    def prepare(self, invocation: InvocationRequest) -> InvocationRequest:
        """Validate and return the exact immutable invocation without native I/O."""
        ...

    def invoke(self, invocation: InvocationRequest) -> InvocationObservation:
        """Dispatch the already authorized turn, using native client deadlines.

        Never retry an ambiguous native call here. The journal claims one call;
        Driver/native readback must reconcile any uncertain result separately.
        """
        ...


def canonical(value) -> str:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False,
    )


def logical_payload(envelope):
    return {"tenant_id": envelope.tenant_id, "message_id": envelope.message_id,
            "command_id": envelope.command_id, "operation_id": envelope.operation_id,
            "authority_id": envelope.authority_id, "authority_incarnation": envelope.authority_incarnation,
            "principal_ref": envelope.principal_ref, "grant_ref": envelope.grant_ref,
            "packet": envelope.packet.model_dump(mode="json")}


def invocation_for(envelope: DeliveryEnvelope, attempt_id: str) -> InvocationRequest:
    selection = {
        "endpoint_id": envelope.endpoint_id,
        "binding_revision": envelope.binding_revision,
        "machine_id": envelope.machine_id,
        "node_id": envelope.node_id,
        "boot_incarnation": envelope.boot_incarnation,
        "target_scope_id": envelope.packet.target_scope_id,
        "target_agent_slot_id": envelope.packet.target_agent_slot_id,
    }
    return InvocationRequest(
        invocation_id=f"delivery-invocation:{attempt_id}",
        attempt_id=attempt_id,
        dispatch_id=f"delivery-dispatch:{attempt_id}",
        runtime_dispatched_receipt_id=f"delivery:{envelope.message_id}:runtime_dispatched",
        message_id=envelope.message_id,
        command_id=envelope.command_id,
        operation_id=envelope.operation_id,
        envelope_digest=hashlib.sha256(canonical(envelope.model_dump(mode="json")).encode()).hexdigest(),
        logical_payload_digest=NodeJournal.payload_digest(logical_payload(envelope)),
        selection_digest=hashlib.sha256(canonical(selection).encode()).hexdigest(),
        accepted_revision=getattr(envelope.packet, "accepted_revision", None),
        accepted_state_digest=envelope.accepted_state_digest,
        envelope=envelope,
    )


class LocalNodeEndpoint:
    """Trusted in-process endpoint with real NodeJournal SQLite commits.

    No network listener or transport authentication is supplied by this adapter.
    Its caller is the local Domain dispatcher, never an untrusted packet sender.
    Grant/revision checks run after obtaining the Node SQLite write lock. This
    version explicitly extends journal/2 tables in the same atomic transaction;
    it never creates a Node identity or a competing Domain authority.
    """

    def __init__(self, journal: NodeJournal, scope_id: str, agent_slot_id: str,
                 driver: InvocationDriver | None = None, response_collector=None, *, clock=None) -> None:
        if journal.SCHEMA_VERSION != "acs-node-journal/2":
            raise ValueError("unsupported NodeJournal schema")
        self.journal, self.scope_id, self.agent_slot_id, self.driver = journal, scope_id, agent_slot_id, driver
        self.response_collector = response_collector
        self.clock = clock if clock is not None else getattr(driver, "clock", None)
        if response_collector is not None and driver is None:
            raise ValueError("response collector requires the bound invocation Driver")
        if driver is not None and driver.evidence_class not in ("fixture_callback", "native_driver_observation"):
            raise ValueError("Driver evidence scope must be explicit")
        with journal._transaction() as connection:
            connection.execute("CREATE TABLE IF NOT EXISTS delivery_invocations ("
                               "operation_id TEXT PRIMARY KEY REFERENCES journal(operation_id),"
                               "invocation_id TEXT NOT NULL UNIQUE,dispatch_id TEXT NOT NULL UNIQUE,"
                               "runtime_dispatched_receipt_id TEXT NOT NULL UNIQUE,"
                               "request_json TEXT NOT NULL,state TEXT NOT NULL,observation_json TEXT)")

    @property
    def identity(self):
        return self.journal.identity

    def descriptor(self):
        return {"machine_id": self.identity.machine_id, "node_id": self.identity.node_id,
                "boot_incarnation": self.identity.boot_incarnation,
                "scope_id": self.scope_id, "agent_slot_id": self.agent_slot_id,
                "supports_invoke": self.driver is not None,
                "evidence_class": self.driver.evidence_class if self.driver else "local_sqlite_commit"}

    def inspect_runtime(self):
        inspect = getattr(self.driver, "inspect_runtime", None)
        return inspect() if callable(inspect) else {"state": "unknown", "harness": "unknown", "session_ref": None}

    def prepare_runtime(self):
        prepare = getattr(self.driver, "prepare_runtime", None)
        return prepare() if callable(prepare) else {"state": "unknown", "harness": "unknown", "session_ref": None,
                                                   "preparation": "unavailable"}

    def receiver_snapshot(self, binding):
        """Observe the bound Native adapter without preparing or invoking it."""
        from runtime.receiver_evidence import unknown_receiver

        if (binding.execution_host_ref != self.identity.machine_id
                or binding.actor_address.rsplit(":", 1)[-1] != self.agent_slot_id):
            raise DeliveryBoundaryRejected("receiver_projection_binding_changed")
        native_identity = getattr(getattr(self.driver, "driver", None), "identity", None)
        if native_identity is not None and (
                native_identity.node_id, native_identity.node_boot_id, native_identity.agent_slot_id) != (
                self.identity.node_id, self.identity.boot_incarnation, self.agent_slot_id):
            raise DeliveryBoundaryRejected("receiver_projection_node_changed")
        read = getattr(self.driver, "receiver_snapshot", None)
        return read(binding) if callable(read) else unknown_receiver(
            binding, reason="native_adapter_contract_unavailable")

    def _check(self, envelope, authorize):
        if (envelope.machine_id != self.identity.machine_id or envelope.node_id != self.identity.node_id
                or envelope.boot_incarnation != self.identity.boot_incarnation
                or envelope.packet.target_scope_id != self.scope_id
                or envelope.packet.target_agent_slot_id != self.agent_slot_id):
            raise DeliveryBoundaryRejected("node_target_changed")
        if self.clock is None:
            if envelope.packet.deadline is not None and datetime.now(UTC) >= envelope.packet.deadline:
                raise DeliveryBoundaryRejected("deadline_expired")
        else:
            if any(self.clock.identity.get(name) != getattr(envelope, name)
                   for name in ("authority_id", "authority_incarnation")):
                raise DeliveryBoundaryRejected("clock_authority_reference_mismatch")
            for name in ("machine_id", "node_id", "boot_incarnation", "endpoint_id"):
                if name in self.clock.identity and self.clock.identity[name] != getattr(envelope, name):
                    raise DeliveryBoundaryRejected("clock_connection_identity_changed")
            try:
                self.clock.require_before(envelope.packet.deadline)
            except ValueError as error:
                raise DeliveryBoundaryRejected("authority_clock_or_deadline_unavailable") from error
        authorized = authorize()
        if not isinstance(authorized, DeliveryEnvelope) or logical_payload(authorized) != logical_payload(envelope):
            raise DeliveryBoundaryRejected("committed_authorization_reference_mismatch")
        if any(getattr(authorized, key) != getattr(envelope, key) for key in (
            "endpoint_id", "binding_revision", "machine_id", "node_id", "boot_incarnation",
        )):
            raise DeliveryBoundaryRejected("authorized_selection_changed")

    def _now(self):
        return self.clock.observation_time() if self.clock is not None else datetime.now(UTC)

    def _receipt(self, connection, envelope, layer, evidence, *, receipt_id=None, preserve_inbox=False):
        encoded = canonical(evidence)
        previous = connection.execute(
            "SELECT evidence_json FROM lifecycle_receipts WHERE operation_id=? AND layer=?",
            (envelope.operation_id, layer),
        ).fetchone()
        if previous:
            if previous[0] != encoded and not preserve_inbox:
                raise OperationIdentityConflict("Node receipt identity changed")
            if preserve_inbox:
                historic = json.loads(previous[0])
                if (historic.get("message_id") != envelope.message_id or historic.get("node_id") != envelope.node_id
                        or historic.get("source") != "local_sqlite_commit"):
                    raise OperationIdentityConflict("historical Inbox receipt differs")
        else:
            connection.execute(
                "INSERT INTO lifecycle_receipts(receipt_id,operation_id,layer,status,observed_at,evidence_json) "
                "VALUES (?,?,?,'observed',?,?)",
                (receipt_id or f"delivery:{envelope.message_id}:{layer}", envelope.operation_id, layer,
                 self._now().isoformat(), encoded),
            )
        layers = [row[0] for row in connection.execute("SELECT layer FROM lifecycle_receipts WHERE operation_id=?",
                                                      (envelope.operation_id,)).fetchall()]
        if any(item not in RECEIPT_LAYERS for item in layers):
            raise OperationIdentityConflict("unknown Node receipt layer")
        highest = max(layers, key=RECEIPT_LAYERS.index)
        connection.execute("UPDATE journal SET state=? WHERE operation_id=?", (highest, envelope.operation_id))
        connection.execute("UPDATE mailbox SET state=? WHERE operation_id=?", (highest, envelope.operation_id))

    def _commit_inbox(self, envelope, authorize):
        payload = logical_payload(envelope)
        # Reuse the journal's typed canonical payload format, not a plain JSON hash.
        digest = self.journal.payload_digest(payload)
        payload_json = canonical({"kind": "json", "value": payload})
        expected = (envelope.operation_id, envelope.command_id, envelope.message_id, "delivery", digest)
        with self.journal._transaction() as connection:
            self._check(envelope, authorize)
            rows = connection.execute(
                "SELECT operation_id,command_id,message_id,operation_kind,payload_sha256 FROM journal "
                "WHERE operation_id=? OR command_id=? OR message_id=?",
                (envelope.operation_id, envelope.command_id, envelope.message_id),
            ).fetchall()
            if rows and (len(rows) != 1 or tuple(rows[0]) != expected):
                raise OperationIdentityConflict("Node command/message/payload identity conflict")
            if not rows:
                connection.execute(
                    "INSERT INTO journal(operation_id,command_id,message_id,operation_kind,payload_sha256,state,"
                    "created_at,machine_id,node_id,boot_incarnation) VALUES (?,?,?,?,?,'recorded',?,?,?,?)",
                    (*expected, self._now().isoformat(), self.identity.machine_id,
                     self.identity.node_id, self.identity.boot_incarnation),
                )
            previous = connection.execute("SELECT command_id,operation_id,payload_sha256,payload_json FROM mailbox WHERE message_id=?",
                                          (envelope.message_id,)).fetchone()
            if previous and tuple(previous) != (envelope.command_id, envelope.operation_id, digest, payload_json):
                raise OperationIdentityConflict("Node Inbox payload differs")
            if not previous:
                connection.execute("INSERT INTO mailbox(message_id,command_id,operation_id,payload_sha256,payload_json,state,created_at) "
                                   "VALUES (?,?,?,?,?,'committed',?)",
                                   (envelope.message_id, envelope.command_id, envelope.operation_id, digest,
                                    payload_json, self._now().isoformat()))
            self._receipt(connection, envelope, "accepted_by_authority",
                          {"operation_id": envelope.operation_id, "source": "committed_domain_outbox"})
            self._receipt(connection, envelope, "target_inbox_committed",
                          {"message_id": envelope.message_id, "node_id": self.identity.node_id,
                           "boot_incarnation": self.identity.boot_incarnation, "source": "local_sqlite_commit"},
                          preserve_inbox=True)
            self._check(envelope, authorize)  # Deadline may elapse while obtaining/writing SQLite pages.

    def invocation(self, envelope: DeliveryEnvelope, attempt_id: str) -> InvocationRequest:
        return invocation_for(envelope, attempt_id)

    def deliver(
        self,
        envelope: DeliveryEnvelope,
        authorize: Callable[[], DeliveryEnvelope],
        invocation: InvocationRequest | None = None,
        mark_dispatched: Callable[[InvocationRequest, dict], None] | None = None,
        read_dispatch_marker: Callable[[InvocationRequest], bool] | None = None,
    ):
        envelope = DeliveryEnvelope.model_validate_json(envelope.model_dump_json(), strict=True)
        self._commit_inbox(envelope, authorize)
        if envelope.packet.activation == "message_only":
            return self.inspect_delivery(envelope.operation_id, "delivered")
        with self.journal._transaction() as connection:
            self._check(envelope, authorize)
            prior = connection.execute("SELECT state,request_json FROM delivery_invocations WHERE operation_id=?",
                                       (envelope.operation_id,)).fetchone()
            if prior and prior[0] != "prepared":
                return self.inspect_delivery(
                    envelope.operation_id,
                    "delivered" if prior[0] == "acknowledged" else "uncertain",
                )
            if invocation is None:
                raise DeliveryBoundaryRejected("immutable_invocation_missing")
            expected_invocation = self.invocation(envelope, invocation.attempt_id)
            if invocation != expected_invocation:
                raise DeliveryBoundaryRejected("immutable_invocation_changed")
            if has_native_attachments(envelope.packet):
                # An earlier Domain marker is possible effect evidence even
                # when this Node still has only its prepared identity.
                if ((read_dispatch_marker is not None and read_dispatch_marker(invocation) is not False)
                        or prior is not None and read_dispatch_marker is None):
                    return self.inspect_delivery(envelope.operation_id, "uncertain")
                reject_native_attachments(invocation)
            if not prior:
                if self.driver is None:
                    raise DeliveryBoundaryRejected("invoke_endpoint_unavailable")
                connection.execute(
                    "INSERT INTO delivery_invocations(operation_id,invocation_id,dispatch_id,"
                    "runtime_dispatched_receipt_id,request_json,state) VALUES (?,?,?,?,?,'prepared')",
                    (envelope.operation_id, invocation.invocation_id, invocation.dispatch_id,
                     invocation.runtime_dispatched_receipt_id, invocation.model_dump_json()),
                )
            elif prior[1] != invocation.model_dump_json():
                raise OperationIdentityConflict("immutable invocation identity changed")
        observation = None
        # Driver preparation is side-effect free. The Domain marker is committed
        # while this SQLite writer fence blocks boot replacement, and strictly
        # before the one native call. From that marker onward, loss is uncertain.
        with self.journal._transaction() as connection:
            self._check(envelope, authorize)
            try:
                prepared = InvocationRequest.model_validate_json(
                    self.driver.prepare(invocation).model_dump_json(), strict=True,
                )
                if prepared != invocation:
                    raise InvocationPreCallRejected("driver_changed_immutable_invocation")
            except InvocationDeferred:
                # Prepared identity and Inbox remain reusable before dispatch.
                raise
            except InvocationPreCallRejected:
                connection.execute(
                    "UPDATE delivery_invocations SET state='pre_call_rejected' WHERE operation_id=?",
                    (envelope.operation_id,),
                )
                connection.execute("COMMIT")
                raise
            except (OSError, RuntimeError, TypeError, ValueError) as error:
                connection.execute(
                    "UPDATE delivery_invocations SET state='pre_call_rejected' WHERE operation_id=?",
                    (envelope.operation_id,),
                )
                # Persist the known pre-call result before propagating it. The
                # transaction context observes no live transaction to roll back.
                connection.execute("COMMIT")
                raise InvocationPreCallRejected("driver_pre_call_rejected") from error

            dispatch_evidence = {
                "invocation_id": invocation.invocation_id,
                "attempt_id": invocation.attempt_id,
                "dispatch_id": invocation.dispatch_id,
                "receipt_id": invocation.runtime_dispatched_receipt_id,
                "message_id": invocation.message_id,
                "command_id": invocation.command_id,
                "operation_id": invocation.operation_id,
                "envelope_digest": invocation.envelope_digest,
                "logical_payload_digest": invocation.logical_payload_digest,
                "selection_digest": invocation.selection_digest,
                "accepted_revision": invocation.accepted_revision,
                "accepted_state_digest": invocation.accepted_state_digest,
                "source": self.driver.evidence_class,
            }
            marker_attempted = False
            marked = False

            def at_native_boundary():
                nonlocal marker_attempted, marked
                if marker_attempted:
                    raise ValueError("dispatch callback cannot be repeated")
                try:
                    self._check(envelope, authorize)
                except (RuntimeError, ValueError) as error:
                    raise InvocationPreCallRejected("delivery_authorization_changed_before_native_call") from error
                marker_attempted = True
                if mark_dispatched is not None:
                    from runtime.delivery import DeliveryRejected
                    from runtime.errors import AuthorizationDenied
                    try:
                        mark_dispatched(invocation, dispatch_evidence)
                    except (AuthorizationDenied, DeliveryRejected) as error:
                        if getattr(error, "state", "blocked") not in {"blocked", "expired"}:
                            raise
                        # A deterministic refusal is pre-call only if a fresh
                        # authoritative read confirms no committed marker.
                        try:
                            absent = read_dispatch_marker is not None and read_dispatch_marker(invocation) is False
                        except Exception:  # noqa: BLE001 -- unknown commit/readback outcome remains uncertain
                            absent = False
                        if absent:
                            marker_attempted = False
                            raise InvocationPreCallRejected("domain_rejected_before_native_dispatch") from error
                        raise RuntimeError("domain_dispatch_marker_outcome_uncertain") from error
                marked = True
                self._receipt(connection, envelope, "runtime_dispatched", dispatch_evidence,
                              receipt_id=invocation.runtime_dispatched_receipt_id)
                connection.execute(
                    "UPDATE delivery_invocations SET state='runtime_dispatched' WHERE operation_id=?",
                    (envelope.operation_id,),
                )

            try:
                if getattr(self.driver, "dispatch_at_native_boundary", False):
                    if mark_dispatched is None:
                        raise InvocationPreCallRejected("domain_dispatch_callback_required")
                    observed = self.driver.invoke(invocation, on_dispatch=at_native_boundary)
                    if not marked:
                        raise InvocationPreCallRejected("native_driver_did_not_cross_dispatch_boundary")
                else:
                    at_native_boundary()
                    observed = self.driver.invoke(invocation)
                observation = InvocationObservation.model_validate_json(
                    observed.model_dump_json(), strict=True,
                )
                if (
                    observation.invocation_id != invocation.invocation_id
                    or observation.dispatch_id != invocation.dispatch_id
                    or observation.runtime_dispatched_receipt_id
                    != invocation.runtime_dispatched_receipt_id
                ):
                    raise ValueError("Driver observation identity differs")
                if len(observation.model_dump_json().encode()) > 65536:
                    raise ValueError("Driver observation exceeds bound")
            except InvocationDeferred:
                if not marker_attempted:
                    raise
                connection.execute("UPDATE delivery_invocations SET state='uncertain' WHERE operation_id=?",
                                   (envelope.operation_id,))
            except InvocationPreCallRejected:
                if not marker_attempted:
                    connection.execute(
                        "UPDATE delivery_invocations SET state='pre_call_rejected' WHERE operation_id=?",
                        (envelope.operation_id,),
                    )
                    connection.execute("COMMIT")
                    raise
                connection.execute("UPDATE delivery_invocations SET state='uncertain' WHERE operation_id=?",
                                   (envelope.operation_id,))
            except (OSError, RuntimeError, TypeError, ValueError):
                connection.execute(
                    "UPDATE delivery_invocations SET state='uncertain' "
                    "WHERE operation_id=? AND state IN ('prepared','runtime_dispatched')",
                    (envelope.operation_id,),
                )
            else:
                # This is readback of the one dispatched call, not renewed authority to invoke.
                if observation.native_ack_ref is not None:
                    self._receipt(connection, envelope, "runtime_acknowledged",
                                  {"invocation_id": invocation.invocation_id,
                                   "dispatch_id": invocation.dispatch_id,
                                   "dispatch_receipt_id": invocation.runtime_dispatched_receipt_id,
                                   "native_dispatch_ref": observation.native_dispatch_ref,
                                   "native_ack_ref": observation.native_ack_ref,
                                   "source": self.driver.evidence_class})
                if observation.response_ref is not None and envelope.packet.schema_version == "acs-delivery/1":
                    if observation.native_ack_ref is None:
                        raise ValueError("response must include native acknowledgment")
                    self._receipt(connection, envelope, "response_received",
                                  {"invocation_id": invocation.invocation_id,
                                   "dispatch_id": invocation.dispatch_id,
                                   "dispatch_receipt_id": invocation.runtime_dispatched_receipt_id,
                                   "response_ref": observation.response_ref, "response": observation.response,
                                   "source": self.driver.evidence_class})
                connection.execute("UPDATE delivery_invocations SET state=?,observation_json=? WHERE operation_id=?",
                                   ("acknowledged" if observation.native_ack_ref else "uncertain",
                                    observation.model_dump_json(), envelope.operation_id))
        if observation is None:
            return self.inspect_delivery(envelope.operation_id, "uncertain")
        return self.inspect_delivery(envelope.operation_id, "delivered" if observation.native_ack_ref else "uncertain")

    def _reconcile_snapshot(self, connection, invocation):
        """Validate persisted input/marker without renewing permission to invoke."""
        envelope = invocation.envelope
        if (envelope.machine_id != self.identity.machine_id or envelope.node_id != self.identity.node_id
                or envelope.boot_incarnation != self.identity.boot_incarnation
                or envelope.packet.target_scope_id != self.scope_id
                or envelope.packet.target_agent_slot_id != self.agent_slot_id):
            raise DeliveryBoundaryRejected("node_reconciliation_target_changed")
        boot = connection.execute("SELECT value FROM node_meta WHERE key='boot_incarnation'").fetchone()
        if boot is None or boot[0] != self.identity.boot_incarnation:
            raise DeliveryBoundaryRejected("node_reconciliation_boot_retired")
        record = connection.execute("SELECT operation_id,invocation_id,dispatch_id,runtime_dispatched_receipt_id,"
            "request_json,state FROM delivery_invocations WHERE operation_id=?", (invocation.operation_id,)).fetchone()
        if record is None:
            return None, False
        stored = InvocationRequest.model_validate_json(record["request_json"], strict=True)
        if (stored != invocation or stored != invocation_for(stored.envelope, stored.attempt_id)
                or (record["invocation_id"], record["dispatch_id"], record["runtime_dispatched_receipt_id"]) !=
                   (invocation.invocation_id, invocation.dispatch_id, invocation.runtime_dispatched_receipt_id)):
            raise DeliveryBoundaryRejected("node_reconciliation_invocation_changed")
        logical = self.journal.payload_digest(logical_payload(envelope))
        journal = connection.execute("SELECT command_id,message_id,operation_kind,payload_sha256 FROM journal "
                                     "WHERE operation_id=?", (invocation.operation_id,)).fetchone()
        if journal is None or tuple(journal) != (invocation.command_id, invocation.message_id, "delivery", logical):
            raise DeliveryBoundaryRejected("node_reconciliation_payload_changed")
        marker = connection.execute("SELECT receipt_id,evidence_json FROM lifecycle_receipts "
            "WHERE operation_id=? AND layer='runtime_dispatched'", (invocation.operation_id,)).fetchone()
        if marker is None:
            return record, False
        evidence = json.loads(marker["evidence_json"])
        expected = {"invocation_id": invocation.invocation_id, "attempt_id": invocation.attempt_id,
            "dispatch_id": invocation.dispatch_id, "receipt_id": invocation.runtime_dispatched_receipt_id,
            "operation_id": invocation.operation_id, "command_id": invocation.command_id,
            "message_id": invocation.message_id, "envelope_digest": invocation.envelope_digest,
            "logical_payload_digest": invocation.logical_payload_digest,
            "selection_digest": invocation.selection_digest, "accepted_revision": invocation.accepted_revision,
            "accepted_state_digest": invocation.accepted_state_digest}
        if (marker["receipt_id"] != invocation.runtime_dispatched_receipt_id
                or any(evidence.get(key) != value for key, value in expected.items())
                or evidence.get("source") != getattr(self.driver, "evidence_class", None)):
            raise DeliveryBoundaryRejected("node_reconciliation_dispatch_marker_changed")
        if record["state"] not in {"runtime_dispatched", "uncertain", "acknowledged"}:
            raise DeliveryBoundaryRejected("node_reconciliation_marker_state_conflict")
        return record, True

    def reconcile_delivery(self, invocation):
        """Read the ORIGINAL input, adding only a positively observed missing ACK.

        Trusted Core callers authorize the actual message reader before entry.
        This method never prepares, invokes, resumes or retries Native input. It
        closes its SQLite read snapshot before any provider readback and rechecks
        the original Node/request/marker before committing additional evidence.
        """
        from runtime.native_delivery import NativeDeliveryAdapter
        from runtime.receiver_contract import NativeAdmissionResult

        invocation = InvocationRequest.model_validate_json(invocation.model_dump_json(), strict=True)
        if (invocation != invocation_for(invocation.envelope, invocation.attempt_id)
                or invocation.envelope.packet.schema_version not in {"acs-message/1", "acs-notice/1"}
                or invocation.envelope.packet.activation != "invoke"):
            raise DeliveryBoundaryRejected("node_reconciliation_requires_original_natural_invocation")
        with closing(self.journal._connect()) as connection:
            connection.execute("BEGIN")
            record, marked = self._reconcile_snapshot(connection, invocation)
        if record is None or not marked:
            return {**self.inspect_delivery(invocation.operation_id, "uncertain"),
                "reason_code": "node_invocation_unavailable" if record is None else "node_dispatch_marker_unavailable"}
        if not isinstance(self.driver, NativeDeliveryAdapter):
            return {**self.inspect_delivery(invocation.operation_id, "uncertain"),
                    "reason_code": "native_reconciliation_unavailable"}
        result = NativeAdmissionResult.model_validate_json(self.driver.reconcile_input(invocation).model_dump_json())
        if result.operation_id != invocation.invocation_id:
            raise DeliveryBoundaryRejected("native_reconciliation_operation_changed")
        if (result.outcome == "accepted" and (result.binding_epoch not in {0, invocation.envelope.binding_revision}
                or result.binding_epoch == 0 and (result.provider_generation is not None or
                    result.reason_code != "legacy_receiving_epoch_unrecorded"))):
            raise DeliveryBoundaryRejected("native_reconciliation_receipt_binding_changed")
        if result.outcome != "accepted":
            return {**self.inspect_delivery(invocation.operation_id, "uncertain"),
                    "native_outcome": result.model_dump(mode="json")}
        with self.journal._transaction() as connection:
            current, marked = self._reconcile_snapshot(connection, invocation)
            if current is None or not marked:
                raise DeliveryBoundaryRejected("node_reconciliation_marker_changed_during_observation")
            self.driver.observation_operation(invocation)
            previous = connection.execute("SELECT evidence_json FROM lifecycle_receipts "
                "WHERE operation_id=? AND layer='runtime_acknowledged'", (invocation.operation_id,)).fetchone()
            if previous is not None:
                evidence = json.loads(previous[0])
                if (evidence.get("invocation_id") != invocation.invocation_id
                        or evidence.get("dispatch_id") != invocation.dispatch_id
                        or evidence.get("dispatch_receipt_id") != invocation.runtime_dispatched_receipt_id
                        or not isinstance(evidence.get("native_ack_ref"), str) or not evidence["native_ack_ref"]):
                    raise DeliveryBoundaryRejected("node_reconciliation_ack_identity_changed")
            else:
                evidence = {"invocation_id": invocation.invocation_id, "dispatch_id": invocation.dispatch_id,
                    "dispatch_receipt_id": invocation.runtime_dispatched_receipt_id,
                    "native_dispatch_ref": result.evidence_ref, "native_ack_ref": result.evidence_ref,
                    "native_input_ref": result.native_input_ref, "source": self.driver.evidence_class,
                    "reconciliation": "original_native_input_query"}
                self._receipt(connection, invocation.envelope, "runtime_acknowledged", evidence)
            connection.execute("UPDATE delivery_invocations SET state='acknowledged' WHERE operation_id=?",
                               (invocation.operation_id,))
        return {**self.inspect_delivery(invocation.operation_id, "uncertain"),
                "native_outcome": result.model_dump(mode="json")}

    def inspect_delivery(self, operation_id, status="uncertain"):
        receipts = [{"receipt_id": item.receipt_id, "layer": item.layer, "evidence": dict(item.evidence)}
                    for item in self.journal.receipts(operation_id)]
        if any(item["layer"] == "runtime_acknowledged" for item in receipts):
            status = "delivered"
        elif status == "delivered":
            # Inbox-only messages need no Native ACK. An invoking delivery does;
            # a caller-supplied optimistic status is not positive Native proof.
            with closing(self.journal._connect()) as connection:
                row = connection.execute("SELECT payload_json FROM mailbox WHERE operation_id=?", (operation_id,)).fetchone()
            packet = json.loads(row[0]).get("value", {}).get("packet", {}) if row else {}
            if packet.get("activation") != "message_only":
                status = "uncertain"
        return {"status": status, "receipts": receipts}

    def collect_response(self, operation_id: str):
        """Collect and project the existing invocation; this path never calls ``invoke``."""
        if self.response_collector is None:
            raise DeliveryBoundaryRejected("response_collector_unavailable")
        with self.journal._connect() as connection:
            row = connection.execute(
                "SELECT request_json,state FROM delivery_invocations WHERE operation_id=?",
                (operation_id,),
            ).fetchone()
        if row is None or row[1] not in {"runtime_dispatched", "acknowledged", "uncertain"}:
            raise DeliveryBoundaryRejected("collectable_invocation_unavailable")
        invocation = InvocationRequest.model_validate_json(row[0], strict=True)
        if invocation.envelope.packet.schema_version != "acs-delivery/1":
            raise DeliveryBoundaryRejected("natural_messages_use_explicit_replies")
        return self.response_collector.collect_and_project(invocation)
