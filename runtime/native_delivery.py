"""Explicit bridge from Delivery preparation to a bound native Driver mutation.

The operator injects the native Driver and a current Node authorization callback.
No model/process is started here; no Grant is derived from sender-controlled text.
"""
from __future__ import annotations

import hashlib
import json
import os
import stat
from dataclasses import asdict

from runtime.codex_driver import (
    AuthorizedOperation,
    CodexAppServerDriver,
    DriverRejected,
    OutcomeUncertain,
)
from runtime.delivery_models import InvocationObservation, InvocationRequest
from runtime.delivery_node import InvocationPreCallRejected, invocation_for
from runtime.opencode_driver import OpenCodeNativeDriver


class NativeDeliveryAdapter:
    evidence_class = "native_driver_observation"
    dispatch_at_native_boundary = True

    def __init__(self, driver, *, authorize_invocation):
        if not isinstance(driver, (CodexAppServerDriver, OpenCodeNativeDriver)) or not callable(authorize_invocation):
            raise TypeError("a bound native Driver and trusted Node authorizer are required")
        self.driver = driver
        self._binding_id = driver.binding_id
        self._journal = driver.journal
        self._journal_path = driver.journal.path
        self._claim_fd = driver._claim_fd
        self._claim_identity = self._claim_signature(self._claim_fd)
        self._claim_token = self._journal.claim_token(self._binding_id, self._claim_fd)
        self._binding = asdict(driver.identity)
        self._authorize_invocation = authorize_invocation

    @staticmethod
    def _claim_signature(descriptor):
        try:
            if type(descriptor) is not int or descriptor < 0:
                raise ValueError("missing claim descriptor")
            observed = os.fstat(descriptor)
            if not stat.S_ISREG(observed.st_mode) or observed.st_nlink < 1:
                raise ValueError("claim is not a linked regular file")
            return observed.st_dev, observed.st_ino, observed.st_mode, observed.st_uid, observed.st_gid, observed.st_nlink
        except (OSError, TypeError, ValueError):
            raise InvocationPreCallRejected("native_claim_unavailable") from None

    def _check_binding(self):
        if (self.driver.binding_id != self._binding_id or self.driver.journal is not self._journal
                or self.driver.journal.path != self._journal_path or self.driver._claim_fd != self._claim_fd
                or self._claim_signature(self.driver._claim_fd) != self._claim_identity
                or asdict(self.driver.identity) != self._binding):
            raise InvocationPreCallRejected("native_binding_or_claim_changed")
        try:
            self._journal.validate_claim(self._claim_token, self._binding_id, self.driver._claim_fd)
        except DriverRejected:
            raise InvocationPreCallRejected("native_kernel_claim_lost") from None

    @staticmethod
    def prompt(invocation):
        # Native Drivers have a text-only turn API; Surface JSON stays structured.
        # Full packet context is rendered deterministically without tool overrides.
        value = {"packet": invocation.envelope.packet.model_dump(mode="json"),
                 "accepted_state_digest": invocation.accepted_state_digest,
                 "summary_provenance": "caller_context; accepted_state_digest is Domain-derived"}
        return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)

    def _operation(self, invocation):
        self._check_binding()
        invocation = InvocationRequest.model_validate_json(invocation.model_dump_json(), strict=True)
        if invocation != invocation_for(invocation.envelope, invocation.attempt_id):
            raise InvocationPreCallRejected("invocation_identity_changed")
        envelope = invocation.envelope
        if (asdict(self.driver.identity) != self._binding
                or (envelope.node_id, envelope.boot_incarnation, envelope.packet.target_agent_slot_id)
                != (self._binding["node_id"], self._binding["node_boot_id"], self._binding["agent_slot_id"])):
            raise InvocationPreCallRejected("native_receiver_binding_changed")
        operation = self._authorize_invocation(invocation, self.driver.identity)
        if (not isinstance(operation, AuthorizedOperation)
                or (operation.operation_id, operation.command_id, operation.message_id)
                != (invocation.invocation_id, invocation.command_id, invocation.message_id)
                or operation.deadline > envelope.packet.deadline):
            raise InvocationPreCallRejected("native_operation_lineage_changed")
        operation.validate()
        self.driver.check_current(operation, self.driver.identity)
        operation.validate()
        self._check_binding()
        return operation

    def prepare(self, invocation):
        try:
            self._operation(invocation)
            self.driver._owned_mutation()
            return invocation
        except (DriverRejected, OutcomeUncertain) as error:
            raise InvocationPreCallRejected("native_binding_not_ready") from error

    def invoke(self, invocation, *, on_dispatch):
        entered = False

        def dispatch():
            nonlocal entered
            try:
                self._check_binding()
                on_dispatch()
            except InvocationPreCallRejected as error:
                # The underlying Driver can now persist its own known pre-call
                # rejection without treating mere intent as a dispatched turn.
                raise DriverRejected("Domain refused the native dispatch boundary") from error
            entered = True

        try:
            operation = self._operation(invocation)
            receipt = self.driver.invoke(operation, self.prompt(invocation), on_dispatch=dispatch)
        except DriverRejected as error:
            if not entered:
                raise InvocationPreCallRejected("native_rejected_before_dispatch") from error
            raise
        if not entered:
            raise InvocationPreCallRejected("native_replay_without_domain_dispatch_marker")
        self._check_binding()
        record = self._journal.read(operation.operation_id)
        if (not isinstance(receipt, dict) or record is None or record["result"] != receipt
                or record["binding_id"] != self.driver.binding_id or record["action"] != "invoke"
                or receipt.get("binding") != self._binding
                or receipt.get("binding_id") != self.driver.binding_id
                or receipt.get("operation_id") != operation.operation_id
                or receipt.get("command_id") != operation.command_id
                or receipt.get("message_id") != operation.message_id
                or receipt.get("receipt_layer") not in {"runtime_dispatched", "runtime_acknowledged"}):
            raise OutcomeUncertain("native journal receipt is not bound to this invocation")
        receipt_hash = hashlib.sha256(json.dumps(receipt, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        reference = f"driver-journal:{self.driver.binding_id}:{operation.operation_id}:{receipt_hash}"
        return InvocationObservation(
            invocation_id=invocation.invocation_id, dispatch_id=invocation.dispatch_id,
            runtime_dispatched_receipt_id=invocation.runtime_dispatched_receipt_id,
            native_dispatch_ref=reference,
            native_ack_ref=reference if receipt["receipt_layer"] == "runtime_acknowledged" else None,
        )
